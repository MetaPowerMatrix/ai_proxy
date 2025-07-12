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
        self.uid = f"proxy_client_001"
        self.responses = []
    
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
            "end_of_stream": end_of_stream  # 明确标记流结束
        }
        
        headers = {
            "uid": self.uid,
            "Content-Type": "application/json"
        }
        
        print(f"发送音频到stream接口 (end_of_stream={end_of_stream})")
        print(f"audio_data bytes: {len(audio_data)}")
        
        response = self.session.post(
            f"{self.base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=30
        )
        print(f"Stream response: {response.json()}")
        print(f"Stream 响应头: {dict(response.headers)}")        

        # response2 = self.send_completions_request()
        # print(f"completions响应头: {dict(response2.headers)}")

        return response.json()
        
    def start_completions_listener(self):
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
                                self.responses.append(data)
                                
                                choice = data.get('choices', [{}])[0]
                                audio = choice.get('audio', '')
                                text = choice.get('text', '')
                                
                                if audio:
                                    print(f"🎵 收到音频: {len(audio)} bytes")
                                if text and text != '\n<end>':
                                    print(f"💬 收到文本: {text}")
                                    
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
    
    def stream_audio_processing(self):
        """改进的音频流处理，包含显式结束标记"""
        audio_chunks = []
        text_parts = []

        response = self.send_completions_request()
        
        if response is None:
            print("❌ 未能获取有效的completions响应")
            return None, None
        
        print(f"✅ 开始处理SSE流 (状态码: {response.status_code})")
        print(f"响应头: {dict(response.headers)}")
        print(f"内容类型: {response.headers.get('content-type', 'unknown')}")
        
        if response.status_code == 200:
            try:
                self._process_sse_stream_improved(response, audio_chunks, text_parts)
                            
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
    
    def _process_sse_stream_improved(self, response, audio_chunks, text_parts):
        try:
            line_count = 0
            start_time = time.time()
            
            for line in response.iter_lines(decode_unicode=True):
                line_count += 1
                
                if line and line.startswith('data: '):
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
                        
                    except json.JSONDecodeError:
                        # 跳过无法解析的数据
                        continue
                
        except Exception as e:
            print(f"❌ SSE流处理异常: {e}")
            import traceback
            traceback.print_exc()
        
        total_time = time.time() - start_time
        print(f"🏁 SSE流处理结束，总耗时: {total_time:.1f}s，处理了 {line_count} 行")
    