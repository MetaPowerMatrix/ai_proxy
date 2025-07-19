#!/usr/bin/env python3
"""
Python Voice Client for MiniCPM-o-2.6
仿照前端VoiceCall_0105.vue实现的语音对话客户端
"""

import asyncio
import json
import base64
import wave
import io
import time
import threading
import queue
import uuid
import logging
from typing import Optional, Dict, Any
import argparse

import pyaudio
import websockets
import httpx
import numpy as np
from sseclient import SSEClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoiceClient:
    def __init__(self, server_host="127.0.0.1", server_port=32550):
        self.server_host = server_host
        self.server_port = server_port
        self.base_url = f"http://{server_host}:{server_port}"
        self.ws_url = f"ws://{server_host}:{server_port}"
        
        # 音频配置
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 256
        self.format = pyaudio.paInt16
        self.chunk_duration = 1.0  # 1秒音频块
        self.chunk_length = int(self.sample_rate * self.chunk_duration)
        
        # 状态管理
        self.uid = str(uuid.uuid4())
        self.is_calling = False
        self.is_recording = False
        self.is_playing = False
        self.stop_requested = False
        
        # 音频相关
        self.audio = pyaudio.PyAudio()
        self.audio_chunks = []
        self.audio_play_queue = queue.Queue()
        
        # WebSocket和HTTP客户端
        self.websocket = None
        self.http_client = httpx.AsyncClient()
        
        logger.info(f"Voice Client initialized with UID: {self.uid}")

    async def upload_config(self, config_data: Optional[Dict] = None) -> bool:
        """上传用户配置到后端"""
        try:
            if config_data is None:
                # 使用默认配置
                config_data = {
                    "videoQuality": "hd",
                    "useAudioPrompt": True,
                    "voiceClonePrompt": "",
                    "assistantPrompt": "You are a helpful AI assistant.",
                    "vadThreshold": 0.5,
                    "audioFormat": "wav",
                    "base64Str": ""  # 可以添加自定义音色
                }
            
            payload = {
                "messages": [{
                    "role": "user",
                    "content": [{
                        "type": "input_audio",
                        "input_audio": {
                            "data": config_data.get("base64Str", ""),
                            "format": config_data.get("audioFormat", "wav")
                        }
                    }, {
                        "type": "options",
                        "options": {
                            "hd_video": config_data.get("videoQuality", "hd"),
                            "use_audio_prompt": config_data.get("useAudioPrompt", True),
                            "vad_threshold": config_data.get("vadThreshold", 0.5),
                            "voice_clone_prompt": config_data.get("voiceClonePrompt", ""),
                            "assistant_prompt": config_data.get("assistantPrompt", "You are a helpful AI assistant.")
                        }
                    }]
                }]
            }
            
            response = await self.http_client.post(
                f"{self.base_url}/api/v1/init_options",
                json=payload,
                headers={"uid": self.uid}
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Config uploaded successfully. Model version: {result.get('choices', {}).get('content', 'Unknown')}")
                return True
            else:
                logger.error(f"Failed to upload config: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error uploading config: {e}")
            return False

    async def stop_message(self) -> bool:
        """停止当前对话"""
        try:
            response = await self.http_client.post(
                f"{self.base_url}/api/v1/stop",
                headers={"uid": self.uid}
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error stopping message: {e}")
            return False

    def encode_audio_to_wav_base64(self, audio_data: np.ndarray) -> str:
        """将音频数据编码为WAV格式的base64字符串"""
        buffer = io.BytesIO()
        
        # 转换为16位PCM
        if audio_data.dtype != np.int16:
            audio_data = (audio_data * 32767).astype(np.int16)
        
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)  # 16位 = 2字节
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_data.tobytes())
        
        buffer.seek(0)
        wav_data = buffer.read()
        return base64.b64encode(wav_data).decode('utf-8')

    def decode_audio_from_base64(self, base64_data: str) -> np.ndarray:
        """从base64字符串解码音频数据"""
        try:
            audio_bytes = base64.b64decode(base64_data)
            buffer = io.BytesIO(audio_bytes)
            
            with wave.open(buffer, 'rb') as wav_file:
                frames = wav_file.readframes(wav_file.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)
                return audio_data
        except Exception as e:
            logger.error(f"Error decoding audio: {e}")
            return np.array([], dtype=np.int16)

    async def websocket_sender(self):
        """WebSocket发送音频数据的协程"""
        try:
            ws_uri = f"{self.ws_url}/ws/stream?uid={self.uid}&service=minicpmo-server"
            
            async with websockets.connect(ws_uri) as websocket:
                self.websocket = websocket
                logger.info("WebSocket connected")
                
                while self.is_recording and not self.stop_requested:
                    if len(self.audio_chunks) >= self.chunk_length:
                        # 合并音频块
                        merged_buffer = np.concatenate(self.audio_chunks[:self.chunk_length])
                        chunk_audio = merged_buffer[:self.chunk_length]
                        
                        # 编码为base64
                        base64_audio = self.encode_audio_to_wav_base64(chunk_audio)
                        
                        # 发送到后端
                        message = {
                            "uid": self.uid,
                            "messages": [{
                                "role": "user",
                                "content": [{
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": base64_audio,
                                        "format": "wav",
                                        "timestamp": str(int(time.time() * 1000))
                                    }
                                }]
                            }]
                        }
                        
                        await websocket.send(json.dumps(message))
                        logger.debug("Audio chunk sent via WebSocket")
                        
                        # 移除已发送的数据，保留剩余部分
                        self.audio_chunks = self.audio_chunks[self.chunk_length:]
                    
                    await asyncio.sleep(0.1)  # 100ms检查间隔
                    
        except Exception as e:
            logger.error(f"WebSocket sender error: {e}")

    async def sse_receiver(self):
        """SSE接收模型响应的协程"""
        try:
            # 建立SSE连接
            payload = {
                "messages": [{
                    "role": "user",
                    "content": [{"type": "none"}]
                }],
                "stream": True
            }
            
            headers = {
                "Content-Type": "application/json",
                "service": "minicpmo-server",
                "uid": self.uid
            }
            
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/api/v1/completions",
                json=payload,
                headers=headers
            ) as response:
                
                if response.status_code != 200:
                    logger.error(f"SSE connection failed: {response.status_code}")
                    return
                
                logger.info("SSE connection established")
                
                async for line in response.aiter_lines():
                    if self.stop_requested:
                        break
                        
                    if line.startswith("data: "):
                        try:
                            data_str = line[6:]  # 移除"data: "前缀
                            if data_str.strip():
                                data = json.loads(data_str)
                                await self.handle_sse_message(data)
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"SSE receiver error: {e}")

    async def handle_sse_message(self, data: Dict[str, Any]):
        """处理SSE消息"""
        try:
            choices = data.get("choices", [])
            if not choices:
                return
                
            choice = choices[0]
            text = choice.get("text", "")
            audio = choice.get("audio")
            
            # 处理文本
            if text and text != "<end>":
                print(f"AI: {text}", end="", flush=True)
            
            # 处理音频
            if audio:
                audio_data = self.decode_audio_from_base64(audio)
                if len(audio_data) > 0:
                    self.audio_play_queue.put(audio_data)
                    
            # 检查是否结束
            if text and "<end>" in text:
                print()  # 换行
                logger.info("Response completed")
                
        except Exception as e:
            logger.error(f"Error handling SSE message: {e}")

    def audio_recorder(self):
        """音频录制线程"""
        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            logger.info("Audio recording started")
            
            while self.is_recording and not self.stop_requested:
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                    audio_chunk = np.frombuffer(data, dtype=np.int16)
                    self.audio_chunks.extend(audio_chunk)
                except Exception as e:
                    logger.error(f"Audio recording error: {e}")
                    break
            
            stream.stop_stream()
            stream.close()
            logger.info("Audio recording stopped")
            
        except Exception as e:
            logger.error(f"Audio recorder error: {e}")

    def audio_player(self):
        """音频播放线程"""
        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.chunk_size
            )
            
            logger.info("Audio player started")
            
            while self.is_calling and not self.stop_requested:
                try:
                    # 等待音频数据
                    if not self.audio_play_queue.empty():
                        audio_data = self.audio_play_queue.get(timeout=1.0)
                        self.is_playing = True
                        
                        # 播放音频
                        stream.write(audio_data.tobytes())
                        
                        self.is_playing = False
                        logger.debug("Audio chunk played")
                    else:
                        time.sleep(0.1)
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Audio playback error: {e}")
                    break
            
            stream.stop_stream()
            stream.close()
            logger.info("Audio player stopped")
            
        except Exception as e:
            logger.error(f"Audio player error: {e}")

    async def start_call(self, config_data: Optional[Dict] = None):
        """开始语音通话"""
        try:
            # 初始化
            self.stop_requested = False
            self.is_calling = True
            self.audio_chunks = []
            
            # 清空播放队列
            while not self.audio_play_queue.empty():
                try:
                    self.audio_play_queue.get_nowait()
                except queue.Empty:
                    break
            
            # 停止之前的会话
            await self.stop_message()
            
            # 上传配置
            if not await self.upload_config(config_data):
                logger.error("Failed to upload config")
                return
            
            # 开始录音
            self.is_recording = True
            record_thread = threading.Thread(target=self.audio_recorder)
            record_thread.daemon = True
            record_thread.start()
            
            # 开始播放
            play_thread = threading.Thread(target=self.audio_player)
            play_thread.daemon = True
            play_thread.start()
            
            # 启动WebSocket发送和SSE接收
            await asyncio.gather(
                self.websocket_sender(),
                self.sse_receiver()
            )
            
        except Exception as e:
            logger.error(f"Error during call: {e}")
        finally:
            await self.stop_call()

    async def start_audio_proxy(self, external_websocket, config_data: Optional[Dict] = None):
        """
        音频代理模式：从外部websocket接收音频数据，转发给大模型，然后将回复转发回去
        
        Args:
            external_websocket: 外部websocket连接，用于接收音频数据和发送回复
            config_data: 可选的配置数据
        """
        try:
            # 初始化
            self.stop_requested = False
            self.is_calling = True
            self.audio_chunks = []
            self.external_ws = external_websocket
            
            # 清空播放队列
            while not self.audio_play_queue.empty():
                try:
                    self.audio_play_queue.get_nowait()
                except queue.Empty:
                    break
            
            # 停止之前的会话
            await self.stop_message()
            
            # 上传配置
            if not await self.upload_config(config_data):
                logger.error("Failed to upload config")
                return
            
            logger.info("Starting audio proxy mode")
            
            # 启动WebSocket发送、SSE接收和外部音频处理
            await asyncio.gather(
                self.websocket_sender_proxy(),
                self.sse_receiver_proxy(),
                self.external_audio_receiver()
            )
            
        except Exception as e:
            logger.error(f"Error during audio proxy: {e}")
        finally:
            await self.stop_call()

    async def external_audio_receiver(self):
        """从外部websocket接收音频数据"""
        try:
            logger.info("External audio receiver started")
            
            while self.is_calling and not self.stop_requested:
                try:
                    # 接收外部websocket的音频数据
                    message = await self.external_ws.receive()
                    
                    if "bytes" in message:
                        # 接收到PCM音频数据
                        pcm_data = message["bytes"]
                        
                        # 将PCM数据转换为numpy数组
                        audio_chunk = np.frombuffer(pcm_data, dtype=np.int16)
                        
                        # 添加到音频缓冲区
                        self.audio_chunks.extend(audio_chunk)
                        
                        logger.debug(f"Received audio chunk: {len(pcm_data)} bytes")
                        
                    elif "text" in message:
                        # 处理文本消息（如果需要）
                        try:
                            data = json.loads(message["text"])
                            logger.debug(f"Received text message: {data}")
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse text message from external websocket")
                    
                except Exception as e:
                    logger.error(f"Error receiving from external websocket: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"External audio receiver error: {e}")

    async def websocket_sender_proxy(self):
        """WebSocket发送音频数据的协程（代理模式）"""
        try:
            ws_uri = f"{self.ws_url}/ws/stream?uid={self.uid}&service=minicpmo-server"
            
            async with websockets.connect(ws_uri) as websocket:
                self.websocket = websocket
                logger.info("WebSocket connected for proxy mode")
                
                while self.is_calling and not self.stop_requested:
                    if len(self.audio_chunks) >= self.chunk_length:
                        # 合并音频块
                        merged_buffer = np.concatenate(self.audio_chunks[:self.chunk_length])
                        chunk_audio = merged_buffer[:self.chunk_length]
                        
                        # 编码为base64
                        base64_audio = self.encode_audio_to_wav_base64(chunk_audio)
                        
                        # 发送到后端
                        message = {
                            "uid": self.uid,
                            "messages": [{
                                "role": "user",
                                "content": [{
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": base64_audio,
                                        "format": "wav",
                                        "timestamp": str(int(time.time() * 1000))
                                    }
                                }]
                            }]
                        }
                        
                        await websocket.send(json.dumps(message))
                        logger.debug("Audio chunk sent via WebSocket (proxy mode)")
                        
                        # 移除已发送的数据，保留剩余部分
                        self.audio_chunks = self.audio_chunks[self.chunk_length:]
                    
                    await asyncio.sleep(0.1)  # 100ms检查间隔
                    
        except Exception as e:
            logger.error(f"WebSocket sender proxy error: {e}")

    async def sse_receiver_proxy(self):
        """SSE接收模型响应的协程（代理模式）"""
        try:
            # 建立SSE连接
            payload = {
                "messages": [{
                    "role": "user",
                    "content": [{"type": "none"}]
                }],
                "stream": True
            }
            
            headers = {
                "Content-Type": "application/json",
                "service": "minicpmo-server",
                "uid": self.uid
            }
            
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/api/v1/completions",
                json=payload,
                headers=headers
            ) as response:
                
                if response.status_code != 200:
                    logger.error(f"SSE connection failed: {response.status_code}")
                    return
                
                logger.info("SSE connection established for proxy mode")
                
                async for line in response.aiter_lines():
                    if self.stop_requested:
                        break
                        
                    if line.startswith("data: "):
                        try:
                            data_str = line[6:]  # 移除"data: "前缀
                            if data_str.strip():
                                data = json.loads(data_str)
                                await self.handle_sse_message_proxy(data)
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"SSE receiver proxy error: {e}")

    async def handle_sse_message_proxy(self, data: Dict[str, Any]):
        """处理SSE消息（代理模式）"""
        try:
            choices = data.get("choices", [])
            if not choices:
                return
                
            choice = choices[0]
            text = choice.get("text", "")
            audio = choice.get("audio")
            
            # 处理文本（可选择是否转发给外部websocket）
            if text and text != "<end>":
                logger.info(f"AI response text: {text}")
                # 可以选择发送文本回复给外部websocket
                try:
                    await self.external_ws.send_text(json.dumps({
                        "type": "text",
                        "content": text
                    }))
                except Exception as e:
                    logger.error(f"Error sending text to external websocket: {e}")
            
            # 处理音频 - 转发给外部websocket
            if audio:
                audio_data = self.decode_audio_from_base64(audio)
                if len(audio_data) > 0:
                    try:
                        # 将音频数据发送回外部websocket
                        await self.external_ws.send_bytes(audio_data.tobytes())
                        logger.debug(f"Audio data forwarded to external websocket: {len(audio_data)} samples")
                    except Exception as e:
                        logger.error(f"Error sending audio to external websocket: {e}")
                    
            # 检查是否结束
            if text and "<end>" in text:
                logger.info("Response completed (proxy mode)")
                
        except Exception as e:
            logger.error(f"Error handling SSE message (proxy mode): {e}")

    async def stop_call(self):
        """停止语音通话"""
        try:
            self.stop_requested = True
            self.is_calling = False
            self.is_recording = False
            
            # 停止后端处理
            await self.stop_message()
            
            # 关闭WebSocket
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            
            logger.info("Voice call stopped")
            
        except Exception as e:
            logger.error(f"Error stopping call: {e}")

    def __del__(self):
        """清理资源"""
        try:
            self.audio.terminate()
        except:
            pass

async def main():
    parser = argparse.ArgumentParser(description="MiniCPM-o Voice Client")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=32550, help="Server port")
    parser.add_argument("--duration", type=int, default=30, help="Call duration in seconds")
    
    args = parser.parse_args()
    
    # 创建客户端
    client = VoiceClient(args.host, args.port)
    
    try:
        print("Starting voice call...")
        print("Speak now! The call will last for {} seconds.".format(args.duration))
        print("Press Ctrl+C to stop early.")
        
        # 创建通话任务
        call_task = asyncio.create_task(client.start_call())
        
        # 设置超时
        try:
            await asyncio.wait_for(call_task, timeout=args.duration)
        except asyncio.TimeoutError:
            print(f"\nCall duration ({args.duration}s) reached.")
        
    except KeyboardInterrupt:
        print("\nStopping call...")
    finally:
        await client.stop_call()
        await client.http_client.aclose()

if __name__ == "__main__":
    asyncio.run(main()) 