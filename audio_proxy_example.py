#!/usr/bin/env python3
"""
音频代理示例
演示如何使用VoiceClient的start_audio_proxy方法
"""

import asyncio
import json
import logging
import websockets
from fastapi import FastAPI, WebSocket
from voice_client import VoiceClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioProxyServer:
    def __init__(self, voice_client_host="127.0.0.1", voice_client_port=32550):
        self.voice_client = VoiceClient(voice_client_host, voice_client_port)
        
    async def handle_external_websocket(self, websocket_url: str):
        """
        连接到外部websocket并启动音频代理
        
        Args:
            websocket_url: 外部websocket的URL
        """
        try:
            async with websockets.connect(websocket_url) as external_ws:
                logger.info(f"Connected to external websocket: {websocket_url}")
                
                # 配置数据（可选）
                config_data = {
                    "videoQuality": "hd",
                    "useAudioPrompt": True,
                    "voiceClonePrompt": "",
                    "assistantPrompt": "You are a helpful AI assistant.",
                    "vadThreshold": 0.5,
                    "audioFormat": "wav",
                    "base64Str": ""
                }
                
                # 启动音频代理
                await self.voice_client.start_audio_proxy(external_ws, config_data)
                
        except Exception as e:
            logger.error(f"Error in audio proxy: {e}")
        finally:
            await self.voice_client.http_client.aclose()

# FastAPI应用示例
app = FastAPI()

@app.websocket("/audio_proxy")
async def audio_proxy_endpoint(websocket: WebSocket):
    """
    WebSocket端点，用于接收外部音频数据并转发给AI
    """
    await websocket.accept()
    logger.info("External websocket connected")
    
    # 创建VoiceClient实例
    voice_client = VoiceClient()
    
    try:
        # 配置数据
        config_data = {
            "assistantPrompt": "You are a helpful AI assistant that responds to voice input.",
            "audioFormat": "wav"
        }
        
        # 启动音频代理
        await voice_client.start_audio_proxy(websocket, config_data)
        
    except Exception as e:
        logger.error(f"Audio proxy error: {e}")
    finally:
        await voice_client.http_client.aclose()
        logger.info("External websocket disconnected")

async def main():
    """主函数 - 直接连接示例"""
    # 示例：连接到指定的websocket
    websocket_url = "ws://localhost:8000/audio_source"  # 替换为实际的websocket URL
    
    proxy_server = AudioProxyServer()
    
    try:
        logger.info("Starting audio proxy...")
        await proxy_server.handle_external_websocket(websocket_url)
    except KeyboardInterrupt:
        logger.info("Audio proxy stopped")
    except Exception as e:
        logger.error(f"Main error: {e}")

if __name__ == "__main__":
    # 运行方式1: 直接连接到外部websocket
    # asyncio.run(main())
    
    # 运行方式2: 作为FastAPI服务器运行
    # uvicorn audio_proxy_example:app --host 0.0.0.0 --port 8001
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001) 