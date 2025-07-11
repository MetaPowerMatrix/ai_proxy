import requests
import json
import base64
import time
import asyncio
from typing import Generator, Tuple

class MiniCPMClient:
    def __init__(self, base_url="http://localhost:32550"):
        self.base_url = base_url
        self.uid = f"python_client_{int(time.time())}"
        
    def send_audio_with_completion_flag(self, audio_base64: str, end_of_stream: bool = True):
        """发送音频并明确标记是否为流的结束"""
        stream_data = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio", 
                    "input_audio": {
                        "data": audio_base64,
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
        
        response = requests.post(
            f"{self.base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=30
        )
        
        return response.status_code == 200
    
    def force_completion(self):
        """强制触发流完成（发送空的停止消息）"""
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
        
        requests.post(
            f"{self.base_url}/api/v1/stream",
            headers=headers,
            json=stop_data,
            timeout=10
        )
    
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
                
                response = requests.post(
                    f"{self.base_url}/api/v1/completions",
                    headers=headers,
                    json={"prompt": ""},
                    stream=True,
                    timeout=(10, 60)  # 10秒连接，60秒读取超时
                )
                
                if response.status_code == 200:
                    return response
                elif response.status_code == 408:
                    print("服务器超时，重试...")
                    time.sleep(2)
                    continue
                else:
                    print(f"请求失败: {response.status_code}")
                    return None
                    
            except requests.exceptions.Timeout:
                print(f"请求超时 (尝试 {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                
        return None

def improved_workflow():
    """改进的工作流程"""
    client = MiniCPMClient()
    
    try:
        # 读取音频文件
        with open("input_audio.wav", "rb") as f:
            audio_bytes = f.read()
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    except FileNotFoundError:
        print("创建测试音频文件...")
        # 创建一个简单的测试音频
        import numpy as np
        import wave
        
        # 生成1秒的440Hz正弦波
        sample_rate = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        wave_data = np.sin(2 * np.pi * 440 * t) * 0.5
        wave_data = (wave_data * 32767).astype(np.int16)
        
        with wave.open("test_audio.wav", "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(wave_data.tobytes())
        
        with open("test_audio.wav", "rb") as f:
            audio_bytes = f.read()
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    
    print("1. 发送音频到stream接口...")
    success = client.send_audio_with_completion_flag(audio_base64, end_of_stream=True)
    
    if not success:
        print("音频发送失败")
        return
    
    print("2. 等待短暂时间让服务器处理...")
    time.sleep(2)
    
    print("3. 强制触发完成状态...")
    client.force_completion()
    
    print("4. 获取completions响应...")
    response = client.get_completions_with_retry()
    
    if response is None:
        print("获取响应失败")
        return
    
    print("5. 处理SSE流...")
    audio_chunks = []
    text_parts = []
    
    try:
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith('data: '):
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                    choice = data.get('choices', [{}])[0]
                    
                    if choice.get('audio'):
                        audio_chunks.append(choice['audio'])
                        print(f"收到音频片段: {len(choice['audio'])} 字符")
                    
                    if choice.get('text'):
                        text_parts.append(choice['text'])
                        print(f"收到文本: {choice['text']}")
                        
                        if '<end>' in choice['text']:
                            print("检测到结束标记")
                            break
                            
                except json.JSONDecodeError:
                    continue
                    
    except Exception as e:
        print(f"处理SSE流时出错: {e}")
    
    print(f"总共收到 {len(audio_chunks)} 个音频片段")
    print(f"完整文本: {''.join(text_parts)}")
    
    return audio_chunks, text_parts

if __name__ == "__main__":
    improved_workflow()