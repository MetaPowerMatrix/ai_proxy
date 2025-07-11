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
import socket

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
        self.uid = f"proxy_client_{int(time.time() * 1000)}"  # 使用时间戳避免uid冲突
    
    def load_audio_file(self, file_path):
        """加载音频文件并转换为base64"""
        with open(file_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode('utf-8')
        return audio_data
        
    def check_service_status(self):
        """检查服务状态"""
        response = requests.get(f"{self.base_url}/health")
        return response
        
    def init_with_chinese_voice(self, reference_audio_file):
        """使用中文语音文件初始化"""
        custom_audio_base64 = self.load_audio_file(reference_audio_file)

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
                            "use_audio_prompt": 0,  # 使用自定义音频
                            "vad_threshold": 0.8,
                            "hd_video": False
                        }
                    }
                ]
            }]
        }

        response = requests.post(
            f"{self.base_url}/init_options",
            json=init_data,
            headers={"uid": self.uid}
        )

        return response.json()

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
    
    def send_audio_with_completion_flag(self, audio_data, end_of_stream=True):
        """发送音频并明确标记是否为流的结束，返回解析后的结果"""
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
            "end_of_stream": end_of_stream  # 明确标记流结束
        }
        
        headers = {
            "uid": self.uid,
            "Content-Type": "application/json"
        }
        
        print(f"发送音频到stream接口 (end_of_stream={end_of_stream})")
        print(f"audio_data bytes: {len(audio_data)}")
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/stream",
                headers=headers,
                json=stream_data,
                timeout=30
            )
            
            print(f"Stream response status: {response.status_code}")
            if response.status_code == 200:
                try:
                    result = response.json()
                    print(f"Stream response: {result}")
                    
                    # 检查是否包含处理完成的数据
                    if isinstance(result, dict) and 'choices' in result:
                        choices = result['choices']
                        if isinstance(choices, dict):
                            finish_reason = choices.get('finish_reason')
                            content = choices.get('content')
                            
                            print(f"💡 检测到完成状态: finish_reason={finish_reason}")
                            
                            if finish_reason == 'done':
                                print("✅ 服务端表示处理已完成")
                                # 检查是否有音频数据
                                if 'audio' in choices:
                                    print("🎵 在Stream响应中发现音频数据")
                                    return {'success': True, 'result': result, 'has_audio': True}
                                else:
                                    print("📝 处理完成但Stream响应中无音频数据")
                                    return {'success': True, 'result': result, 'has_audio': False}
                    
                    return {'success': True, 'result': result, 'has_audio': False}
                except Exception as parse_error:
                    print(f"Stream response (非JSON): {response.text[:200]}")
                    return {'success': True, 'result': None, 'has_audio': False}
            else:
                print(f"Stream请求失败: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            print(f"Stream请求异常: {e}")
            return {'success': False, 'error': str(e)}
    
    def force_completion(self):
        """强制触发流完成（发送空的停止消息）"""
        print("发送强制完成信号...")
        stop_data = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "stop_response"
                }]
            }]
        }
        
        headers = {
            "uid": self.uid,
            "Content-Type": "application/json"
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/stream",
                headers=headers,
                json=stop_data,
                timeout=10
            )
            print(f"强制完成信号响应: {response.status_code}")
        except Exception as e:
            print(f"发送强制完成信号异常: {e}")
    
    def get_completions_with_retry(self, max_retries=3):
        """带重试机制的completions请求"""
        for attempt in range(max_retries):
            try:
                print(f"尝试获取completions (第{attempt+1}次)")
                
                headers = {
                    "uid": self.uid,
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache"
                }
                
                response = self.session.post(
                    f"{self.base_url}/api/v1/completions",
                    headers=headers,
                    json={"prompt": ""},
                    stream=True,
                    timeout=(10, 60)  # 10秒连接，60秒读取超时
                )
                
                if response.status_code == 200:
                    print(f"Completions请求成功 (第{attempt+1}次)")
                    return response
                elif response.status_code == 408:
                    print("服务器超时，重试...")
                    time.sleep(2)
                    continue
                else:
                    print(f"请求失败: {response.status_code}, {response.text[:200]}")
                    return None
                    
            except requests.exceptions.Timeout:
                print(f"请求超时 (尝试 {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            except Exception as e:
                print(f"请求异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                
        return None
    
    def get_completions_with_quick_timeout(self, max_retries=1):
        """快速超时的completions请求（用于已完成的处理）"""
        for attempt in range(max_retries):
            try:
                print(f"快速completions请求 (第{attempt+1}次，超时15秒)")
                
                headers = {
                    "uid": self.uid,
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache"
                }
                
                response = self.session.post(
                    f"{self.base_url}/api/v1/completions",
                    headers=headers,
                    json={"prompt": ""},
                    stream=True,
                    timeout=(5, 15)  # 5秒连接，15秒读取超时（因为处理已完成）
                )
                
                if response.status_code == 200:
                    print(f"快速completions请求成功 (第{attempt+1}次)")
                    return response
                else:
                    print(f"快速请求失败: {response.status_code}")
                    return None
                    
            except requests.exceptions.Timeout:
                print(f"快速请求超时 (尝试 {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
            except Exception as e:
                print(f"快速请求异常: {e}")
                return None
                
        return None

    def send_audio_request(self, audio_data=None, image_data=None):
        """发送音频请求到MiniCPM-o服务器 - 智能版本"""
        
        if not audio_data:
            return None
            
        # 1. 发送音频到stream接口并明确标记结束
        stream_result = self.send_audio_with_completion_flag(audio_data, end_of_stream=True)
        
        if not stream_result['success']:
            print("❌ 音频发送失败")
            return None
        
        # 2. 检查Stream响应是否已包含完整结果
        if stream_result.get('result') and isinstance(stream_result['result'], dict):
            choices = stream_result['result'].get('choices', {})
            if isinstance(choices, dict) and choices.get('finish_reason') == 'done':
                print("🎯 Stream响应显示处理已完成，检查是否需要额外的completions请求...")
                
                # 如果Stream响应中已有音频数据，直接返回
                if stream_result.get('has_audio'):
                    print("✅ Stream响应中已包含音频数据，无需额外请求")
                    # 构造一个兼容的响应对象
                    return self._create_mock_response(stream_result['result'])
                
                # 如果没有音频数据，尝试短暂的completions请求
                print("📝 Stream响应无音频数据，尝试简短的completions请求...")
                time.sleep(1)  # 较短等待
                
                # 跳过强制完成信号，因为已经完成了
                response = self.get_completions_with_quick_timeout(max_retries=1)
                
                if response and response.status_code == 200:
                    print("✅ 获取到completions响应")
                    return response
                else:
                    print("⚠️ Completions请求未获得有效响应，但Stream处理已完成")
                    return self._create_mock_response(stream_result['result'])
        
        # 3. 如果Stream响应未完成，执行完整流程
        print("🔄 Stream响应未显示完成，执行完整处理流程...")
        
        # 等待服务器处理
        print("等待服务器处理音频...")
        time.sleep(2)
        
        # 强制触发完成状态
        self.force_completion()
        
        # 获取completions响应
        print("获取completions响应...")
        response = self.get_completions_with_retry()
        
        if response is None:
            print("❌ 获取completions响应失败")
            return None
        
        print("✅ 成功获取completions响应")
        return response
    
    def _create_mock_response(self, result_data):
        """创建一个模拟的响应对象用于兼容现有流程"""
        class MockResponse:
            def __init__(self, data):
                self.status_code = 200
                self.headers = {'content-type': 'application/json'}
                self._data = data
                
            def json(self):
                return self._data
                
            def iter_lines(self, decode_unicode=True):
                # 如果有音频数据，构造SSE格式
                if 'choices' in self._data:
                    choices = self._data['choices']
                    if isinstance(choices, dict):
                        data_line = f"data: {json.dumps({'choices': [choices]})}"
                        yield data_line
                        yield "data: [DONE]"
        
        return MockResponse(result_data)


    def stream_audio_processing(self, wav_file_path):
        """改进的音频流处理，包含显式结束标记"""
        audio_chunks = []
        text_parts = []

        print("开始改进的音频流处理...")
        audio_base64 = self.load_audio_file(wav_file_path)
        response = self.send_audio_request(audio_data=audio_base64)
        
        if response is None:
            print("❌ 未能获取有效的completions响应")
            return None, None
        
        print(f"✅ 开始处理SSE流 (状态码: {response.status_code})")
        print(f"响应头: {dict(response.headers)}")
        print(f"内容类型: {response.headers.get('content-type', 'unknown')}")
        
        if response.status_code == 200:
            try:
                # 根据响应类型智能选择超时时间
                # 如果是MockResponse说明使用了快速路径，用较短超时
                timeout_seconds = 30 if hasattr(response, '_data') else 300
                
                # 使用改进的SSE流处理
                self._process_sse_stream_improved(response, audio_chunks, text_parts, timeout_seconds)
                            
            except Exception as e:
                print(f"流处理错误: {e}")
                import traceback
                traceback.print_exc()
                return None, None
        else:
            print(f"❌ Completions请求失败: {response.status_code}")
            try:
                print(f"错误信息: {response.text[:300]}")
            except:
                print("无法读取错误信息")
            return None, None
        
        print(f"🎉 流处理完成: 收到 {len(audio_chunks)} 个音频片段, 文本长度 {len(''.join(text_parts))}")
        return audio_chunks, ''.join(text_parts)
    
    def _process_sse_data(self, data, audio_chunks, text_parts):
        """处理SSE数据"""
        if 'choices' in data and data['choices']:
            choice = data['choices'][0] if isinstance(data['choices'], list) else data['choices']
            
            if 'audio' in choice and choice['audio']:
                audio_base64 = choice['audio']
                pcm_data = base64_to_pcm(audio_base64)
                if pcm_data[0] is not None:  # 检查解析是否成功
                    audio_chunks.append(pcm_data)
                    print(f"收到音频片段，长度: {len(audio_base64)}")
            
            if 'text' in choice and choice['text']:
                text = choice['text'].replace('<end>', '')
                text_parts.append(text)
                print(f"收到文本: {text}")
                
                # 检查是否结束
                if '<end>' in choice['text']:
                    print("收到结束标记")
                    return True  # 表示结束
        return False
    
    def _process_sse_stream_improved(self, response, audio_chunks, text_parts, timeout_seconds=300):
        """改进的SSE流处理方法，支持智能超时"""
        timeout_desc = "快速" if timeout_seconds < 60 else "标准"
        print(f"开始处理SSE流... ({timeout_desc}模式，超时{timeout_seconds}秒)")
        
        try:
            line_count = 0
            start_time = time.time()
            last_data_time = start_time
            
            for line in response.iter_lines(decode_unicode=True):
                line_count += 1
                current_time = time.time()
                
                if line and line.startswith('data: '):
                    last_data_time = current_time
                    data_str = line[6:]  # 移除 'data: ' 前缀
                    
                    # 检查结束标记
                    if data_str.strip() == '[DONE]':
                        print("✅ 收到 [DONE] 标记，流处理完成")
                        break
                    
                    try:
                        data = json.loads(data_str)
                        choice = data.get('choices', [{}])[0] if data.get('choices') else {}
                        
                        # 处理音频数据
                        if choice.get('audio'):
                            audio_base64 = choice['audio']
                            pcm_data = base64_to_pcm(audio_base64)
                            if pcm_data[0] is not None:  # 检查解析是否成功
                                audio_chunks.append(pcm_data)
                                print(f"📦 收到音频片段: {len(audio_base64)} 字符")
                        
                        # 处理文本数据
                        if choice.get('text'):
                            text = choice['text']
                            text_parts.append(text)
                            print(f"📝 收到文本: {text}")
                            
                            # 检查文本中的结束标记
                            if '<end>' in text:
                                print("✅ 检测到文本结束标记")
                                break
                        
                        # 显示处理进度（快速模式少显示）
                        progress_interval = 5 if timeout_seconds < 60 else 10
                        if line_count % progress_interval == 0:
                            elapsed = current_time - start_time
                            print(f"⏱️ 已处理 {line_count} 行，耗时 {elapsed:.1f}s")
                            
                    except json.JSONDecodeError:
                        # 跳过无法解析的数据
                        continue
                
                # 动态超时检查
                if current_time - start_time > timeout_seconds:
                    print(f"⚠️ 处理超时({timeout_seconds}秒)，停止读取")
                    break
                
                # 无数据超时检查（快速模式更严格）
                no_data_timeout = min(30, timeout_seconds // 2)
                if current_time - last_data_time > no_data_timeout:
                    print(f"⚠️ {no_data_timeout}秒无数据，可能连接断开")
                    break
                    
        except Exception as e:
            print(f"❌ SSE流处理异常: {e}")
            import traceback
            traceback.print_exc()
        
        total_time = time.time() - start_time
        print(f"🏁 SSE流处理结束，总耗时: {total_time:.1f}s，处理了 {line_count} 行")
    
    def _process_sse_stream(self, response, audio_chunks, text_parts):
        """处理SSE流数据，统一的流处理方法"""
        print("开始处理SSE流数据...")
        
        buffer = ""
        chunk_count = 0
        start_time = time.time()
        
        try:
            # 使用较小的chunk size和更频繁的超时检查
            
            # 尝试设置socket超时（如果可能的话）
            try:
                # 获取underlying socket并设置超时
                sock = response.raw._connection.sock
                if sock and hasattr(sock, 'settimeout'):
                    sock.settimeout(60)
                    print("🔧 已设置socket读取超时: 60秒")
            except Exception as e:
                print(f"⚠️ 无法设置socket超时: {e}，使用应用层超时控制")
            
            last_data_time = time.time()
            no_data_timeout = 120  # 2分钟没有数据则超时
            
            for chunk in response.iter_content(chunk_size=512, decode_unicode=True):
                chunk_count += 1
                current_time = time.time()
                
                # 检查总体超时（10分钟）
                if current_time - start_time > 600:
                    print("⚠️ 总体处理超时(10分钟)，停止读取")
                    break
                
                if chunk:
                    last_data_time = current_time
                    buffer += chunk
                    
                    if chunk_count % 5 == 1:  # 每5个chunk显示一次进度
                        print(f"📦 已处理 {chunk_count} 个数据块，耗时 {current_time - start_time:.1f}s")
                    
                    # 处理完整的SSE事件
                    events_processed = 0
                    while "\n\n" in buffer:
                        event_data, buffer = buffer.split("\n\n", 1)
                        events_processed += 1
                        
                        # 解析SSE事件
                        if self._parse_sse_event(event_data, audio_chunks, text_parts):
                            print("✅ 收到结束标记，处理完成")
                            return True
                    
                    if events_processed > 0:
                        print(f"📨 处理了 {events_processed} 个SSE事件")
                
                else:
                    # 检查是否长时间没有数据
                    if current_time - last_data_time > no_data_timeout:
                        print(f"⚠️ {no_data_timeout}秒没有收到数据，可能连接已断开")
                        break
                    
                    print("📭 收到空数据块...")
                    time.sleep(0.1)  # 短暂等待
                    
        except Exception as e:
            print(f"❌ 流处理过程中出错: {e}")
            # 不要重新抛出异常，让上层代码继续处理
            
        total_time = time.time() - start_time
        print(f"🏁 流处理结束，总耗时: {total_time:.1f}s，处理了 {chunk_count} 个数据块")
        return False
    
    def _parse_sse_event(self, event_data, audio_chunks, text_parts):
        """解析单个SSE事件"""
        lines = event_data.strip().split('\n')
        data_line = None
        event_type = None
        
        for line in lines:
            if line.startswith('data: '):
                data_line = line[6:]  # 移除 'data: ' 前缀
            elif line.startswith('event: '):
                event_type = line[7:]  # 移除 'event: ' 前缀
        
        if data_line and data_line.strip() and data_line != '[DONE]':
            try:
                data = json.loads(data_line)
                print(f"🔍 解析SSE事件: type={event_type}, data_type={type(data)}")
                
                return self._process_sse_data(data, audio_chunks, text_parts)
                
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON解析失败: {e}")
                print(f"   原始数据: {data_line[:200]}...")
                return False
        elif data_line == '[DONE]':
            print("🏁 收到 [DONE] 标记")
            return True
            
        return False
    