import requests
import json
import base64
import wave
import io
import numpy as np
from sseclient import SSEClient
import librosa
import soundfile as sf
import time
import threading
import os
import tempfile


def base64_to_pcm(base64_audio_data):
    """将base64音频数据解码为PCM数据"""
    
    # 解码base64
    try:
        audio_bytes = base64.b64decode(base64_audio_data)
    except Exception as e:
        print(f"Base64解码失败: {e}")
        return None, None, None
    
    # 使用BytesIO创建文件对象
    audio_buffer = io.BytesIO(audio_bytes)
    
    try:
        # 方法1: 使用wave库解析WAV文件
        with wave.open(audio_buffer, 'rb') as wav_file:
            # 获取音频参数
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            
            print(f"音频参数: {frames}帧, {sample_rate}Hz, {channels}声道, {sample_width}字节/样本")
            
            # 读取PCM数据
            pcm_data = wav_file.readframes(frames)
            
            # 转换为numpy数组
            if sample_width == 1:
                dtype = np.uint8
            elif sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                dtype = np.float32
                
            pcm_array = np.frombuffer(pcm_data, dtype=dtype)

            # 如果sample_rate不是16000，则重采样到16000
            # if sample_rate != 16000:
            #     pcm_array = librosa.resample(pcm_array, orig_sr=sample_rate, target_sr=16000)
            #     sample_rate = 16000
            
            # 如果是多声道，重塑数组
            if channels > 1:
                pcm_array = pcm_array.reshape(-1, channels)
            
            return pcm_array, sample_rate, channels
            
    except Exception as e:
        print(f"WAV解析失败: {e}")

def save_pcm_as_wav(pcm_data, sample_rate, channels, output_file):
    """将PCM数据保存为WAV文件"""
    try:
        # 使用soundfile保存
        sf.write(output_file, pcm_data, sample_rate)
        print(f"音频已保存到: {output_file}")
    except Exception as e:
        print(f"保存音频失败: {e}")


class MiniCPMClient:
    def __init__(self, base_url="http://localhost:32550"):
        self.base_url = base_url
        self.session = requests.Session()
        self.uid = f"proxy_client_001"
        self.responses = []
        self.session_id = None
        
        # 线程控制变量
        self.completions_thread = None
        self.should_stop_listening = False
        self.auto_restart_listener = True
        self.current_audio_callback = None
        self.current_text_callback = None

    def set_session_id(self, session_id):
        self.session_id = session_id

    def load_audio_file(self, file_path):
        """加载音频文件并转换为base64"""
        with open(file_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode('utf-8')
        return audio_data
        
    def check_service_status(self):
        """检查服务状态"""
        response = requests.get(f"{self.base_url}/health")
        return response
        
    def send_audio_with_completion_flag(self, audio_data, end_of_stream=True):
        """发送音频并明确标记是否为流的结束"""
        stream_data = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio", 
                    "input_audio": {
                        "data": audio_data,
                        "format": "wav",
                        "timestamp": str(int(time.time() * 1000))
                    }
                }]
            }],
            "end_of_stream": False
        }
        
        headers = {
            "uid": self.uid,
            "Content-Type": "application/json"
        }
        
        response = self.session.post(
            f"{self.base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=30
        )

        return response.json()

    def send_completions_request(self) -> requests.Response:
        headers = {
            "uid": self.uid,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
        
        response = self.session.post(
            f"{self.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            stream=True,
            timeout=(30, 60)
        )
        
        return response
    
    def stop_completions_listener(self):
        """停止completions监听器"""
        self.should_stop_listening = True
        if (self.completions_thread and 
            self.completions_thread.is_alive() and 
            self.completions_thread != threading.current_thread()):
            print("🛑 停止completions监听器...")
            self.completions_thread.join(timeout=2)
        else:
            print("🛑 设置停止标志...")

    def restart_completions_listener(self):
        """重启completions监听器"""
        if self.current_audio_callback and self.current_text_callback:
            print("🔄 重启completions监听器...")
            # 如果是在监听线程内部调用，只设置停止标志
            if threading.current_thread() == self.completions_thread:
                self.should_stop_listening = True
                # 延迟重启，让当前线程先退出
                def delayed_restart():
                    time.sleep(0.5)
                    if not self.should_stop_listening:  # 检查是否仍需要重启
                        return
                    self.should_stop_listening = False
                    self.start_completions_listener(
                        self.current_audio_callback, 
                        self.current_text_callback, 
                        self.auto_restart_listener
                    )
                
                restart_thread = threading.Thread(target=delayed_restart)
                restart_thread.daemon = True
                restart_thread.start()
            else:
                # 外部调用，正常停止后重启
                self.stop_completions_listener()
                time.sleep(0.5)
                self.start_completions_listener(
                    self.current_audio_callback, 
                    self.current_text_callback, 
                    self.auto_restart_listener
                )

    def start_completions_listener(self, on_audio_done, on_text_done, auto_restart=True):
        """启动completions接口监听"""
        # 保存回调函数供重启使用
        self.current_audio_callback = on_audio_done
        self.current_text_callback = on_text_done
        self.auto_restart_listener = auto_restart
        self.should_stop_listening = False
        
        def listen():
            exit_reason = "unknown"  # 记录退出原因
            connection_error = None  # 记录连接错误
            
            try:
                response = requests.post(
                    f"{self.base_url}/completions",
                    json={},
                    headers={"uid": self.uid, "Accept": "text/event-stream"},
                    stream=True
                )

                print("✅ Completions连接建立")

                # SSE消息缓冲
                current_event = None
                current_data = None
                received_end_signal = False

                try:
                    for line in response.iter_lines():
                        # 检查是否需要停止
                        if self.should_stop_listening:
                            exit_reason = "manual_stop"
                            print("🛑 收到停止信号，退出监听")
                            break
                        
                        line_text = line.decode().strip()
                        
                        # 空行表示消息结束
                        if not line_text:
                            if current_event == "message" and current_data:
                                try:
                                    data = json.loads(current_data)
                                    
                                    completed = data.get('completed', False)
                                    choice = data.get('choices', [{}])[0]
                                    audio_base64 = choice.get('audio', '')
                                    text = choice.get('text', '')
                                    finish_reason = choice.get('finish_reason', '')
                                    
                                    if completed:
                                        print(f"🏁 全部发送完毕，统计数据{data}")
                                        received_end_signal = True
                                        exit_reason = "end_signal"

                                    # 检测结束条件
                                    if (text == '\n<end>' or 
                                        finish_reason in ['stop', 'completed'] or 
                                        text.endswith('<end>') or
                                        finish_reason == 'done'):
                                        print("🏁 检测到结束标志")
                                        received_end_signal = True
                                        exit_reason = "end_signal"

                                    if audio_base64:
                                        pcm_data = base64_to_pcm(audio_base64)
                                        if (hasattr(pcm_data[0], 'shape') and 
                                            pcm_data[0].size > 0):
                                            print(f"📦 收到音频片段: {len(audio_base64)} 字符")
                                            on_audio_done(pcm_data[0])

                                    if text and text != '\n<end>':
                                        print(f"💬 收到文本: {text}")
                                        on_text_done(text)
                                    
                                    # 如果收到结束信号，退出循环
                                    if received_end_signal:
                                        print("🔚 完成当前会话，退出监听线程")
                                        break
                                        
                                except json.JSONDecodeError as e:
                                    print(f"JSON解析错误: {e}, 数据: {current_data}")
                            
                            # 重置缓冲
                            current_event = None
                            current_data = None
                            
                        # 解析事件类型
                        elif line_text.startswith("event: "):
                            print(f"🔄 收到事件: {line_text}")
                            current_event = line_text[7:]  # 去掉 "event: "
                            
                        # 解析数据
                        elif line_text.startswith("data: "):
                            current_data = line_text[6:]  # 去掉 "data: "

                        else:
                            print(f"🔄 收到空行，继续接收: {line_text}")
                    
                    # 如果循环正常结束且没有设置退出原因，说明是流结束
                    if exit_reason == "unknown":
                        exit_reason = "stream_ended"
                        
                except requests.exceptions.Timeout as e:
                    exit_reason = "timeout"
                    connection_error = f"连接超时: {e}"
                    print(f"⏰ 连接超时: {e}")
                    
                except requests.exceptions.ConnectionError as e:
                    exit_reason = "connection_error"
                    connection_error = f"连接错误: {e}"
                    print(f"🔌 连接错误: {e}")
                    
                except requests.exceptions.ChunkedEncodingError as e:
                    exit_reason = "server_disconnect"
                    connection_error = f"服务器断开连接: {e}"
                    print(f"🔌 服务器断开连接: {e}")
                    
                except requests.exceptions.RequestException as e:
                    exit_reason = "request_error"
                    connection_error = f"请求错误: {e}"
                    print(f"🌐 网络请求错误: {e}")

            except Exception as e:
                exit_reason = "exception"
                connection_error = f"监听异常: {e}"
                print(f"💥 Completions监听错误: {e}")
            
            # 分析退出原因并决定重启策略
            self._handle_listener_exit(exit_reason, connection_error)
        
        self.completions_thread = threading.Thread(target=listen)
        self.completions_thread.daemon = True
        self.completions_thread.start()

    def _handle_listener_exit(self, exit_reason, connection_error=None):
        """处理监听器退出，根据不同原因采取不同策略"""
        print("📻 监听线程结束")
        
        # 根据退出原因提供详细信息
        exit_messages = {
            "manual_stop": "🛑 手动停止",
            "end_signal": "🏁 正常完成（收到结束信号）",
            "stream_ended": "📡 服务器流结束",
            "timeout": "⏰ 连接超时",
            "connection_error": "🔌 网络连接问题",
            "server_disconnect": "🔌 服务器主动断开连接",
            "request_error": "🌐 网络请求错误", 
            "exception": "💥 程序异常",
            "unknown": "❓ 未知原因"
        }
        
        print(f"🔍 退出原因: {exit_messages.get(exit_reason, exit_reason)}")
        if connection_error:
            print(f"🔍 详细信息: {connection_error}")
        
        # 决定是否重启
        should_restart = self.auto_restart_listener and not self.should_stop_listening
        
        # 根据不同退出原因设置不同的重启延迟
        restart_delays = {
            "manual_stop": 0,      # 手动停止，不重启
            "end_signal": 1,       # 正常结束，快速重启
            "stream_ended": 1,     # 流结束，快速重启
            "timeout": 5,          # 超时，延迟重启
            "connection_error": 10, # 连接错误，较长延迟
            "server_disconnect": 3, # 服务器断开，中等延迟
            "request_error": 8,    # 请求错误，较长延迟
            "exception": 5,        # 异常，中等延迟
            "unknown": 5           # 未知，中等延迟
        }
        
        # 手动停止不重启
        if exit_reason == "manual_stop":
            should_restart = False
        
        if should_restart:
            delay = restart_delays.get(exit_reason, 5)
            print(f"🔄 {delay}秒后自动重启监听器...")
            
            # 创建延迟重启线程，避免线程自join问题
            def delayed_restart():
                time.sleep(delay)
                if self.auto_restart_listener and not self.should_stop_listening:
                    print(f"🚀 重新启动监听器（原因：{exit_messages.get(exit_reason, exit_reason)}）...")
                    self.start_completions_listener(
                        self.current_audio_callback, 
                        self.current_text_callback, 
                        self.auto_restart_listener
                    )
            
            restart_thread = threading.Thread(target=delayed_restart)
            restart_thread.daemon = True
            restart_thread.start()
        else:
            print("🚫 不会自动重启监听器")

    def analyze_audio_quality(self, audio_file):
        """分析音频质量，返回关键指标"""
        try:
            with wave.open(audio_file, 'rb') as wav_file:
                # 获取音频参数
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                duration = frames / sample_rate
                
                # 读取音频数据
                audio_data = wav_file.readframes(frames)
                
                # 转换为numpy数组进行分析
                if sample_width == 1:
                    audio_array = np.frombuffer(audio_data, dtype=np.uint8)
                elif sample_width == 2:
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                elif sample_width == 4:
                    audio_array = np.frombuffer(audio_data, dtype=np.int32)
                else:
                    audio_array = np.frombuffer(audio_data, dtype=np.float32)
                
                # 计算音频质量指标
                rms = np.sqrt(np.mean(audio_array.astype(np.float64) ** 2))
                max_amplitude = np.max(np.abs(audio_array))
                
                # 计算信噪比估计
                signal_power = np.mean(audio_array.astype(np.float64) ** 2)
                noise_estimate = np.var(audio_array.astype(np.float64))
                snr_estimate = 10 * np.log10(signal_power / (noise_estimate + 1e-10))
                
                quality_info = {
                    'duration': duration,
                    'sample_rate': sample_rate,
                    'channels': channels,
                    'sample_width': sample_width,
                    'frames': frames,
                    'rms': rms,
                    'max_amplitude': max_amplitude,
                    'snr_estimate': snr_estimate,
                    'dynamic_range': max_amplitude / (rms + 1e-10)
                }
                
                return quality_info
                
        except Exception as e:
            print(f"音频质量分析失败: {e}")
            return None


    def suggest_vad_threshold(self, quality_info):
        """根据音频质量建议VAD阈值"""
        if not quality_info:
            return 0.8  # 默认值
        
        # 基于音频质量动态调整VAD阈值
        base_threshold = 0.8
        
        # 如果音频时长太短，降低阈值
        if quality_info['duration'] < 2.0:
            base_threshold -= 0.2
            
        # 如果RMS值较低（音量小），降低阈值
        if quality_info['rms'] < 1000:
            base_threshold -= 0.1
            
        # 如果信噪比较低，降低阈值
        if quality_info['snr_estimate'] < 10:
            base_threshold -= 0.1
            
        # 如果动态范围较低，降低阈值
        if quality_info['dynamic_range'] < 2.0:
            base_threshold -= 0.1
            
        # 确保阈值在合理范围内
        suggested_threshold = max(0.1, min(0.9, base_threshold))
        
        return suggested_threshold


    def init_with_adaptive_vad(self, audio_file):
        """使用自适应VAD阈值初始化客户端"""
        print("🔍 分析音频质量...")
        quality_info = self.analyze_audio_quality(audio_file)
        
        if quality_info:
            print(f"📊 音频质量分析结果:")
            print(f"   时长: {quality_info['duration']:.2f}s")
            print(f"   采样率: {quality_info['sample_rate']}Hz")
            print(f"   RMS: {quality_info['rms']:.2f}")
            print(f"   信噪比估计: {quality_info['snr_estimate']:.2f}dB")
            print(f"   动态范围: {quality_info['dynamic_range']:.2f}")
            
            # 基于质量分析建议VAD阈值
            suggested_threshold = self.suggest_vad_threshold(quality_info)
            print(f"💡 建议VAD阈值: {suggested_threshold:.2f}")
            
            # 使用建议的阈值初始化
            return self.init_with_custom_vad_threshold(audio_file, suggested_threshold)
        else:
            print("⚠️ 无法分析音频质量，使用默认阈值")
            return self.init_with_chinese_voice(audio_file)


    def init_with_custom_vad_threshold(self, audio_file, vad_threshold):
        """使用自定义VAD阈值初始化客户端"""
        try:
            custom_audio_base64 = self.load_audio_file(audio_file)
            
            init_data = {
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": custom_audio_base64,
                                "format": "wav"
                            }
                        },
                        {
                            "type": "options",
                            "options": {
                                "voice_clone_prompt": "你是一个AI助手。你能接受视频，音频和文本输入并输出语音和文本。模仿输入音频中的声音特征。",
                                "assistant_prompt": "作为助手，你将使用这种声音风格说话。",
                                "use_audio_prompt": 0,
                                "use_optimized_vad": False,
                                "vad_threshold": 0.7,
                                # "vad_threshold": vad_threshold,  # 使用自定义阈值
                                "hd_video": False
                            }
                        }
                    ]
                }]
            }
            
            response = self.session.post(
                f"{self.base_url}/init_options",
                json=init_data,
                headers={"uid": self.uid}
            )
            
            print(f"✅ 使用VAD阈值 {vad_threshold:.2f} 初始化成功")
            return response.json()
            
        except Exception as e:
            print(f"❌ 自定义VAD阈值初始化失败: {e}")
            raise

    def split_audio_into_chunks(self, audio_file, num_chunks=2):
        """将音频文件分成指定数量的片段"""
        try:
            with wave.open(audio_file, 'rb') as wav_file:
                # 获取音频参数
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                
                # 读取所有音频数据
                audio_data = wav_file.readframes(frames)
                
                # 计算每个片段的大小
                chunk_size = len(audio_data) // num_chunks
                
                chunks = []
                for i in range(num_chunks):
                    start = i * chunk_size
                    if i == num_chunks - 1:  # 最后一个片段包含剩余所有数据
                        end = len(audio_data)
                    else:
                        end = start + chunk_size
                    
                    chunk_data = audio_data[start:end]
                    
                    # 创建临时WAV文件
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                        with wave.open(temp_file.name, 'wb') as chunk_wav:
                            chunk_wav.setnchannels(channels)
                            chunk_wav.setsampwidth(sample_width)
                            chunk_wav.setframerate(sample_rate)
                            chunk_wav.writeframes(chunk_data)
                        
                        # 读取临时文件并转换为base64
                        temp_file.seek(0)
                        with open(temp_file.name, 'rb') as f:
                            chunk_base64 = base64.b64encode(f.read()).decode('utf-8')
                        
                        chunks.append({
                            'index': i + 1,
                            'data': chunk_base64,
                            'size': len(chunk_data),
                            'duration': len(chunk_data) / (sample_rate * channels * sample_width)
                        })
                        
                        # 删除临时文件
                        os.unlink(temp_file.name)
                
                print(f"🔪 音频分片完成: {len(chunks)} 个片段")
                return chunks
                
        except Exception as e:
            print(f"❌ 音频分片失败: {e}")
            return []


    def test_chunked_audio_processing(self, audio_file, skip_chunked_audio=False):
        # 分片处理
        if not skip_chunked_audio:
            chunks = self.split_audio_into_chunks(audio_file, num_chunks=2)
            if not chunks:
                print("❌ 音频分片失败")
                return
        else:
            chunks = [{"index": 1, "data": self.load_audio_file(audio_file), "size": len(audio_file), "duration": len(audio_file) / (16000 * 1 * 2)}]
        
        start_time = time.time()
        successful_chunks = 0
        failed_chunks = 0
        
        
        for i, chunk in enumerate(chunks):
            try:
                # 判断是否为最后一个片段
                is_last_chunk = (i == len(chunks) - 1)
                
                # 发送音频片段
                stream_result = self.send_audio_with_completion_flag(
                    chunk['data'], 
                    end_of_stream=is_last_chunk
                )
                choices = stream_result.get('choices', {})
                
                if choices.get('content'):
                    text_content = choices['content']
                    if text_content == 'success':
                        successful_chunks += 1
                    else:
                        failed_chunks += 1
                
            except Exception as e:
                print(f"   💥 片段 {chunk['index']} 处理异常: {e}")
                failed_chunks += 1
            
            # 片段间短暂延迟
            time.sleep(0.1)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        success_rate = (successful_chunks / len(chunks)) * 100 if chunks else 0
        print(f"成功率: {success_rate:.1f}% 总耗时: {total_time:.1f}s")
        
        return None, None

    def start_completions_listener_with_sse(self, on_audio_done, on_text_done):
        """启动SSE流completions接口监听"""
        def listen():
            try:
                # response = requests.post(
                #     f"{self.base_url}/completions",
                #     json={},
                #     headers={"uid": self.uid, "Accept": "text/event-stream"},
                #     stream=True
                # )
                response = self.send_completions_request()
                print("✅ SSE Completions连接建立")

                # 添加调试信息
                print(f"📊 响应状态码: {response.status_code}")
                print(f"📊 响应头: {dict(response.headers)}")

                client = SSEClient(response)
                for event in client.events():
                    if event.event == "message":
                        try:
                            data = json.loads(event.data)
                            
                            # 检查错误情况
                            if 'error' in data:
                                print(f"❌ 服务端错误: {data['error']}")
                                continue
                            
                            choice = data.get('choices', [{}])[0]
                            audio_base64 = choice.get('audio', '')
                            text = choice.get('text', '')
                            finish_reason = choice.get('finish_reason', '')

                            # 检查多种结束条件
                            if (text == '\n<end>' or 
                                finish_reason in ['stop', 'completed'] or 
                                text.endswith('<end>')):
                                print("🏁 检测到结束标志，停止接收")

                            if audio_base64:
                                pcm_data = base64_to_pcm(audio_base64)
                                if (hasattr(pcm_data[0], 'shape') and 
                                    pcm_data[0].size > 0):
                                    print(f"📦 收到音频片段: {len(audio_base64)} 字符")
                                    on_audio_done(pcm_data[0])

                            if text and text != '\n<end>':
                                print(f"💬 收到文本: {text}")
                                on_text_done(text)
                                
                        except json.JSONDecodeError as e:
                            print(f"JSON解析错误: {e}")        
            except Exception as e:
                print(f"Completions监听错误: {e}")
        
        self.completions_thread = threading.Thread(target=listen)
        self.completions_thread.daemon = True
        self.completions_thread.start()
