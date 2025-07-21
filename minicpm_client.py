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
        
        # 方法2: 使用librosa作为备选
        try:
            audio_buffer.seek(0)
            audio_array, sr = librosa.load(audio_buffer, sr=None, mono=False)
            
            # librosa返回的是float32格式，范围[-1,1]
            # 转换为int16 PCM格式
            if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                pcm_array = (audio_array * 32767).astype(np.int16)
            else:
                pcm_array = audio_array
                
            channels = 1 if len(pcm_array.shape) == 1 else pcm_array.shape[0]
            
            return pcm_array, sr, channels
            
        except Exception as e2:
            print(f"Librosa解析也失败: {e2}")
            return None, None, None

def merge_pcm_chunks(pcm_chunks_list):
    """合并多个PCM音频片段"""
    if not pcm_chunks_list:
        return None
    
    # 假设所有片段具有相同的采样率和声道数
    merged_pcm = np.concatenate(pcm_chunks_list, axis=0)
    return merged_pcm

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
            "end_of_stream": False  # 明确标记流结束
        }
        
        headers = {
            "uid": self.uid,
            "Content-Type": "application/json"
        }
        
        # print(f"发送音频到stream接口 (end_of_stream={end_of_stream})")
        # print(f"audio_data bytes: {len(audio_data)}")
        
        response = self.session.post(
            f"{self.base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=30
        )
        # print(f"Stream response: {response.json()}")
        # print(f"Stream 响应头: {dict(response.headers)}")        

        # response2 = self.send_completions_request()
        # print(f"completions响应头: {dict(response2.headers)}")

        return response.json()
        
    def start_completions_listener(self, on_audio_done, on_text_done):
        """启动completions接口监听"""
        def listen():
            try:
                response = requests.post(
                    f"{self.base_url}/completions",
                    json={},
                    headers={"uid": self.uid, "Accept": "text/event-stream"},
                    stream=True
                )
                
                print("✅ Completions连接建立")
                for line in response.iter_lines():
                    if line:
                        line_text = line.decode()
                        if line_text.startswith("data: "):
                            try:
                                data = json.loads(line_text[6:])
                                # self.responses.append(data)
                                
                                choice = data.get('choices', [{}])[0]
                                audio_base64 = choice.get('audio', '')
                                text = choice.get('text', '')
                                
                                if audio_base64:
                                    pcm_data = base64_to_pcm(audio_base64)
                                    print(f"pcm_data: {pcm_data}")
                                    # 正确检查pcm_data是否有效
                                    if (hasattr(pcm_data[0], 'shape') and  # 确保是NumPy数组
                                        pcm_data[0].size > 0):  # 使用size检查数组是否为空
                                        print(f"📦 收到音频片段: {len(audio_base64)} 字符")
                                        on_audio_done(pcm_data[0])

                                if text and text != '\n<end>':
                                    print(f"💬 收到文本: {text}")
                                    on_text_done(text)
                        
                            except json.JSONDecodeError:
                                print(f"原始数据: {line_text}")
            except Exception as e:
                print(f"Completions监听错误: {e}")
        
        self.completions_thread = threading.Thread(target=listen)
        self.completions_thread.daemon = True
        self.completions_thread.start()

    def send_completions_request(self) -> requests.Response:
        """发送completions请求获取SSE流（旧版本，保留兼容性）"""
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
                                # "use_optimized_vad": True,
                                # "vad_threshold": 0.2,
                                "vad_threshold": vad_threshold,  # 使用自定义阈值
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

    def split_audio_into_chunks(self, audio_file, num_chunks=20):
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
            chunks = self.split_audio_into_chunks(audio_file, num_chunks=5)
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
                
                # if 'audio' in choices:
                #     print(f"   🎵 收到音频数据: {len(choices['audio'])} 字符")
                
                if choices.get('content'):
                    text_content = choices['content']
                    if text_content == 'success':
                        successful_chunks += 1
                    else:
                        failed_chunks += 1
                
                # 检查完成状态
                # if choices.get('finish_reason') == 'done':
                #     print(f"   🏁 片段 {chunk['index']} 标记为完成")
                        
            except Exception as e:
                print(f"   💥 片段 {chunk['index']} 处理异常: {e}")
                failed_chunks += 1
            
            # 片段间短暂延迟
            time.sleep(0.1)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        response2 = self.send_completions_request()
        # print(f"completions响应头: {dict(response2.headers)}")

        success_rate = (successful_chunks / len(chunks)) * 100 if chunks else 0
        print(f"成功率: {success_rate:.1f}% 总耗时: {total_time:.1f}s")
        
        if success_rate >= 90:
            print(f"   🎉 优秀! 分片发送非常稳定")
        elif success_rate >= 70:
            print(f"   ✅ 良好! 大部分片段发送成功")
        else:
            print(f"   ⚠️ 需要优化! 发送成功率较低")
        
        return None, None
