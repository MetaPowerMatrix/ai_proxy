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
                json=stream_data
            )
            print(f"Stream response: {response.status_code}")
        
        # 2. 发送completions请求获取生成的音频
        headers = {"uid": self.uid}
        response = self.session.post(
            f"{self.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""}  # 可以为空，因为音频已通过stream发送
        )
        
        return response

    def stream_audio_processing(self, wav_file_path):
        audio_chunks = []
        text_parts = []

        audio_base64 = self.load_audio_file(wav_file_path)
        response = self.send_audio_request(audio_data=audio_base64)
        
        print(f"completions response: {response.status_code}")
        if response.status_code == 200:
            # 实时处理每个音频片段
            try:
                client_sse = SSEClient(response)
                
                for event in client_sse.events():
                    if event.data:
                        try:
                            data = json.loads(event.data)
                            # 获取音频数据
                            if 'choices' in data and data['choices']:
                                choice = data['choices'][0] if isinstance(data['choices'], list) else data['choices']
                                
                                if 'audio' in choice and choice['audio']:
                                    audio_base64 = choice['audio']
                                    audio_chunks.append(base64_to_pcm(audio_base64))
                                    print(f"收到音频片段，长度: {len(audio_base64)}")
                                
                                if 'text' in choice and choice['text']:
                                    text = choice['text'].replace('<end>', '')
                                    text_parts.append(text)
                                    print(f"收到文本: {text}")
                                    
                                    # 检查是否结束
                                    if '<end>' in choice['text']:
                                        print("收到结束标记")
                                        break
                                    
                        except json.JSONDecodeError:
                            continue
                            
            except Exception as e:
                print(f"流处理错误: {e}")
                return None, None
        
        return audio_chunks, ''.join(text_parts)
    