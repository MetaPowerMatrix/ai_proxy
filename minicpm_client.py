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
        self.uid = "proxy_client_001"
    
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
        """发送completions请求获取SSE流"""
        headers = {
            "uid": self.uid,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "stream": "true"
        }
        
        # 使用session并设置适当的超时
        # 注意：这里不设置读取超时，让它在流处理中单独控制
        response = self.session.post(
            f"{self.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            stream=True,  # 重要：必须设置为True
            timeout=(30, 30)  # 只设置连接超时，读取超时在流处理中控制
        )
        print(f"completions响应头: {dict(response.headers)}")        
        
        return response
    
    def send_audio_request(self, audio_data=None, image_data=None):
        """发送音频请求到MiniCPM-o服务器"""
        
        # 1. 如果有音频数据，先发送到stream接口
        if audio_data:
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
                }]
            }
            
            if image_data:
                stream_data["messages"][0]["content"].insert(0, {
                    "type": "image_data",
                    "image_data": {
                        "data": image_data
                    }
                })
            
            # 发送stream请求
            print(f"audio_data bytes: {len(audio_data)}")
            headers = {"uid": self.uid, "Content-Type": "application/json"}
            response = self.session.post(
                f"{self.base_url}/api/v1/stream",
                headers=headers,
                json=stream_data,
                stream=True,
                timeout=(30, 300)
            )
            print(f"Stream response: {response.json()}")
            time.sleep(1)

            # 2. 发送completions请求获取生成的音频
            response = self.send_completions_request()
            print(f"completions response 1: {response.json()}")

            return response
        
        return None


    def stream_audio_processing(self, wav_file_path):
        audio_chunks = []
        text_parts = []

        audio_base64 = self.load_audio_file(wav_file_path)
        response = self.send_audio_request(audio_data=audio_base64)
        
        print(f"completions response 2: {response.json()}")
        if response and response.status_code == 200:
            # 检查响应头
            print(f"响应头: {dict(response.headers)}")
            print(f"内容类型: {response.headers.get('content-type', 'unknown')}")
            
            # 实时处理每个音频片段
            try:
                # 方法1: 直接处理流数据（更可靠的方法）
                print("开始处理SSE流数据...")
                self._process_sse_stream(response, audio_chunks, text_parts)
                            
            except Exception as e:
                print(f"流处理错误: {e}")
                import traceback
                traceback.print_exc()
                return None, None
        else:
            print(f"请求失败或响应无效: {response}")
            if response:
                print(f"响应状态: {response.status_code}")
                print(f"响应文本: {response.text[:200]}...")
        
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
    