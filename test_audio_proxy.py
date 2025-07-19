#!/usr/bin/env python3
"""
音频代理测试客户端
用于测试VoiceClient的音频代理功能
"""

import asyncio
import json
import logging
import wave
import numpy as np
import websockets
import pyaudio
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioProxyTestClient:
    def __init__(self, proxy_url="ws://localhost:8001/audio_proxy"):
        self.proxy_url = proxy_url
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 1024
        self.format = pyaudio.paInt16
        self.audio = pyaudio.PyAudio()
        self.is_recording = False
        self.is_playing = False
        
    def generate_test_audio(self, duration=1.0, frequency=440):
        """生成测试音频数据（正弦波）"""
        sample_count = int(self.sample_rate * duration)
        t = np.linspace(0, duration, sample_count, False)
        wave_data = np.sin(frequency * 2.0 * np.pi * t)
        # 转换为16位PCM
        audio_data = (wave_data * 32767).astype(np.int16)
        return audio_data
    
    def load_audio_file(self, file_path):
        """从WAV文件加载音频数据"""
        try:
            with wave.open(str(file_path), 'rb') as wav_file:
                if wav_file.getnchannels() != self.channels or wav_file.getframerate() != self.sample_rate:
                    logger.warning(f"Audio file format mismatch. Expected: {self.channels} channels, {self.sample_rate} Hz")
                
                frames = wav_file.readframes(wav_file.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)
                return audio_data
        except Exception as e:
            logger.error(f"Error loading audio file: {e}")
            return None

    async def test_with_generated_audio(self):
        """使用生成的测试音频测试代理"""
        try:
            async with websockets.connect(self.proxy_url) as websocket:
                logger.info("Connected to audio proxy")
                
                # 生成1秒的测试音频
                test_audio = self.generate_test_audio(duration=1.0, frequency=440)
                logger.info(f"Generated test audio: {len(test_audio)} samples")
                
                # 分块发送音频数据
                chunk_size = self.sample_rate // 4  # 0.25秒的音频块
                for i in range(0, len(test_audio), chunk_size):
                    chunk = test_audio[i:i + chunk_size]
                    await websocket.send(chunk.tobytes())
                    logger.debug(f"Sent audio chunk: {len(chunk)} samples")
                    await asyncio.sleep(0.1)  # 模拟实时音频流
                
                # 等待并接收回复
                logger.info("Waiting for AI response...")
                try:
                    while True:
                        response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        
                        if isinstance(response, str):
                            # 文本回复
                            data = json.loads(response)
                            if data.get("type") == "text":
                                logger.info(f"AI Text Response: {data.get('content', '')}")
                        elif isinstance(response, bytes):
                            # 音频回复
                            audio_data = np.frombuffer(response, dtype=np.int16)
                            logger.info(f"Received audio response: {len(audio_data)} samples")
                            # 这里可以播放音频或保存到文件
                            await self.play_audio(audio_data)
                            
                except asyncio.TimeoutError:
                    logger.info("No more responses, test completed")
                
        except Exception as e:
            logger.error(f"Test error: {e}")

    async def test_with_microphone(self):
        """使用麦克风录音测试代理"""
        try:
            async with websockets.connect(self.proxy_url) as websocket:
                logger.info("Connected to audio proxy")
                logger.info("Starting microphone recording for 5 seconds...")
                
                # 开始录音
                self.is_recording = True
                record_task = asyncio.create_task(self.record_and_send_audio(websocket))
                
                # 接收回复
                receive_task = asyncio.create_task(self.receive_responses(websocket))
                
                # 录音5秒
                await asyncio.sleep(5.0)
                self.is_recording = False
                
                # 等待任务完成
                await asyncio.gather(record_task, receive_task, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"Microphone test error: {e}")

    async def record_and_send_audio(self, websocket):
        """录音并发送音频数据"""
        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            logger.info("Recording started...")
            
            while self.is_recording:
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                    await websocket.send(data)
                    await asyncio.sleep(0.01)  # 短暂延迟
                except Exception as e:
                    logger.error(f"Recording error: {e}")
                    break
            
            stream.stop_stream()
            stream.close()
            logger.info("Recording stopped")
            
        except Exception as e:
            logger.error(f"Record and send error: {e}")

    async def receive_responses(self, websocket):
        """接收代理的回复"""
        try:
            while self.is_recording or not self.is_recording:  # 继续接收直到手动停止
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    
                    if isinstance(response, str):
                        # 文本回复
                        data = json.loads(response)
                        if data.get("type") == "text":
                            logger.info(f"AI Text Response: {data.get('content', '')}")
                    elif isinstance(response, bytes):
                        # 音频回复
                        audio_data = np.frombuffer(response, dtype=np.int16)
                        logger.info(f"Received audio response: {len(audio_data)} samples")
                        await self.play_audio(audio_data)
                        
                except asyncio.TimeoutError:
                    if not self.is_recording:
                        break
                    continue
                    
        except Exception as e:
            logger.error(f"Receive responses error: {e}")

    async def play_audio(self, audio_data):
        """播放音频数据"""
        try:
            if self.is_playing:
                return  # 避免重叠播放
                
            self.is_playing = True
            
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.chunk_size
            )
            
            # 播放音频
            stream.write(audio_data.tobytes())
            stream.stop_stream()
            stream.close()
            
            self.is_playing = False
            logger.info("Audio playback completed")
            
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
            self.is_playing = False

    def __del__(self):
        """清理资源"""
        try:
            self.audio.terminate()
        except:
            pass

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Audio Proxy Test Client")
    parser.add_argument("--proxy-url", default="ws://localhost:8001/audio_proxy", 
                        help="Audio proxy WebSocket URL")
    parser.add_argument("--mode", choices=["generated", "microphone"], default="generated",
                        help="Test mode: generated audio or microphone")
    
    args = parser.parse_args()
    
    client = AudioProxyTestClient(args.proxy_url)
    
    try:
        if args.mode == "generated":
            logger.info("Testing with generated audio...")
            await client.test_with_generated_audio()
        else:
            logger.info("Testing with microphone...")
            await client.test_with_microphone()
            
    except KeyboardInterrupt:
        logger.info("Test stopped by user")
    except Exception as e:
        logger.error(f"Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 