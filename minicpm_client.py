import requests
import json
import time
import threading
from urllib.parse import urlencode
import base64

class MiniCPMClient:
    def __init__(self, base_url="http://localhost:32550", uid="user123"):
        self.base_url = base_url
        self.uid = uid
        self.completions_thread = None
        self.responses = []

    def check_service_status(self):
        """检查服务状态"""
        response = requests.get(f"{self.base_url}/health")
        return response
    
    def load_audio_file(self, file_path):
        """加载音频文件并转换为base64"""
        with open(file_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode()
        return audio_data

    # 中文语音克隆示例
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


    def start_completions_listener(self, completions_callback=None):
        """启动completions接口监听
        
        Args:
            completions_callback: 回调函数，接收参数(audio_data: str, audio_length: int, text: str)
        """
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
                                
                                # 处理音频数据
                                if audio:
                                    if completions_callback:
                                        try:
                                            completions_callback(audio, len(audio), None)
                                        except Exception as e:
                                            print(f"音频回调函数错误: {e}")
                                    else:
                                        print(f"🎵 收到音频: {len(audio)} bytes")
                                
                                # 处理文本数据
                                if text and text != '\n<end>':
                                    if completions_callback:
                                        try:
                                            completions_callback(None, None, text)
                                        except Exception as e:
                                            print(f"文本回调函数错误: {e}")
                                    else:
                                        print(f"💬 收到文本: {text}")
                                    
                            except json.JSONDecodeError:
                                print(f"原始数据: {line_text}")
            except Exception as e:
                print(f"Completions监听错误: {e}")
        
        self.completions_thread = threading.Thread(target=listen)
        self.completions_thread.daemon = True
        self.completions_thread.start()
    
    def send_audio_stream(self, audio_base64):
        """发送音频流到stream接口"""
        stream_data = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_base64,
                        "timestamp": time.time()
                    }
                }]
            }]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/stream",
                json=stream_data,
                headers={"uid": self.uid}
            )
            
            result = response.json()
            finish_reason = result.get('choices', {}).get('finish_reason', '')
            
            print(f"📤 Stream响应: {finish_reason}")
            return finish_reason
            
        except Exception as e:
            print(f"发送音频流错误: {e}")
            return "error"
