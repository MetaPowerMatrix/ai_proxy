#!/usr/bin/env python3
"""
Janus WebRTC Python客户端
用于与ESP32-S3语音助手进行音频通信（静态SRTP版本）
以及支持WebRTC音频流传输

功能：
1. 通过Janus Gateway连接到ESP32-S3
2. 发送和接收Opus音频数据
3. 支持静态SRTP密钥配置
4. 实时音频播放和录制
5. WebRTC音频流传输支持

依赖：
pip install requests websockets pyaudio opus-python cryptography aiortc av

作者：Claude Code
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from queue import Queue

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioReceiveTrack(MediaStreamTrack):
    """
    接收来自Janus的音频轨道
    """
    kind = "audio"

    def __init__(self, audio_queue):
        super().__init__()
        self.audio_queue = audio_queue
        self.audio_buffer = b""
        self.buffer_size = 16000 * 2  # 1秒的16kHz 16位音频

    async def recv(self):
        """
        接收音频帧并处理
        """
        frame = await super().recv()
        
        # 将音频帧转换为PCM数据
        if frame:
            # 获取音频数据
            audio_data = frame.to_ndarray()
            
            # 如果是多声道，转换为单声道
            if len(audio_data.shape) > 1 and audio_data.shape[0] > 1:
                audio_data = np.mean(audio_data, axis=0)
            elif len(audio_data.shape) > 1:
                audio_data = audio_data[0]  # 取第一个声道
            
            # 转换为16位PCM格式
            if audio_data.dtype != np.int16:
                # 假设输入是float32格式，范围[-1, 1]
                audio_data = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            
            # 添加到缓冲区
            audio_bytes = audio_data.tobytes()
            self.audio_buffer += audio_bytes
            
            # 当缓冲区达到一定大小时，处理音频数据
            if len(self.audio_buffer) >= self.buffer_size:
                self.audio_queue.put(self.audio_buffer)
                logger.info(f"收到音频数据: {len(self.audio_buffer)} 字节")
                self.audio_buffer = b""
        
        return frame

class AudioSendTrack(MediaStreamTrack):
    """
    发送音频轨道到Janus
    """
    kind = "audio"

    def __init__(self, response_queue):
        super().__init__()
        self.response_queue = response_queue
        self._timestamp = 0
        self._sample_rate = 16000
        self._samples_per_frame = int(self._sample_rate * 0.02)  # 20ms frames
        self._current_audio = None
        self._audio_position = 0

    async def recv(self):
        """
        发送音频帧
        """
        import av
        
        # 检查是否需要新的音频数据
        if self._current_audio is None or self._audio_position >= len(self._current_audio):
            if not self.response_queue.empty():
                audio_data = self.response_queue.get()
                self._current_audio = np.frombuffer(audio_data, dtype=np.int16)
                self._audio_position = 0
                logger.info(f"获取新的音频数据: {len(self._current_audio)} 样本")
        
        # 准备音频帧数据
        if self._current_audio is not None and self._audio_position < len(self._current_audio):
            # 获取当前帧的音频数据
            end_pos = min(self._audio_position + self._samples_per_frame, len(self._current_audio))
            frame_data = self._current_audio[self._audio_position:end_pos]
            
            # 如果数据不够一帧，用零填充
            if len(frame_data) < self._samples_per_frame:
                padding = np.zeros(self._samples_per_frame - len(frame_data), dtype=np.int16)
                frame_data = np.concatenate([frame_data, padding])
            
            self._audio_position = end_pos
            
            # 如果音频播放完毕，清空当前音频
            if self._audio_position >= len(self._current_audio):
                self._current_audio = None
                self._audio_position = 0
        else:
            # 没有音频数据，发送静音
            frame_data = np.zeros(self._samples_per_frame, dtype=np.int16)
        
        # 创建音频帧
        frame = av.AudioFrame.from_ndarray(
            frame_data.reshape(1, -1), 
            format='s16', 
            layout='mono'
        )
        frame.sample_rate = self._sample_rate
        frame.pts = self._timestamp
        
        self._timestamp += self._samples_per_frame
        return frame

class JanusSignaling:
    """
    Janus WebRTC网关信令处理
    """
    def __init__(self, url, plugin="janus.plugin.audiobridge"):
        self.url = url
        self.plugin = plugin
        self.websocket = None
        self.session_id = None
        self.handle_id = None
        self.transaction_id = 0

    async def connect(self):
        """连接到Janus网关"""
        import websockets
        
        try:
            self.websocket = await websockets.connect(self.url)
            logger.info(f"已连接到Janus网关: {self.url}")
            
            # 创建会话
            await self.create_session()
            
            # 附加到audiobridge插件
            await self.attach_plugin()
            
            return True
        except Exception as e:
            logger.error(f"连接Janus网关失败: {e}")
            return False

    async def create_session(self):
        """创建Janus会话"""
        self.transaction_id += 1
        message = {
            "janus": "create",
            "transaction": str(self.transaction_id)
        }
        
        await self.websocket.send(json.dumps(message))
        response = await self.websocket.recv()
        data = json.loads(response)
        
        if data.get("janus") == "success":
            self.session_id = data["data"]["id"]
            logger.info(f"Janus会话创建成功: {self.session_id}")
        else:
            raise Exception(f"创建Janus会话失败: {data}")

    async def attach_plugin(self):
        """附加到audiobridge插件"""
        self.transaction_id += 1
        message = {
            "janus": "attach",
            "plugin": self.plugin,
            "transaction": str(self.transaction_id),
            "session_id": self.session_id
        }
        
        await self.websocket.send(json.dumps(message))
        response = await self.websocket.recv()
        data = json.loads(response)
        
        if data.get("janus") == "success":
            self.handle_id = data["data"]["id"]
            logger.info(f"已附加到audiobridge插件: {self.handle_id}")
        else:
            raise Exception(f"附加插件失败: {data}")

    async def join_room(self, room_id, display_name="Agent"):
        """加入音频房间"""
        self.transaction_id += 1
        message = {
            "janus": "message",
            "transaction": str(self.transaction_id),
            "session_id": self.session_id,
            "handle_id": self.handle_id,
            "body": {
                "request": "join",
                "room": room_id,
                "display": display_name,
                "pin": "1234",
                "muted": False,
                "quality": 4
            }
        }
        
        await self.websocket.send(json.dumps(message))
        response = await self.websocket.recv()
        data = json.loads(response)
        
        if data.get("janus") == "success":
            logger.info(f"已加入音频房间: {room_id}")
        else:
            raise Exception(f"加入房间失败: {data}")

    async def send_offer(self, offer):
        """发送SDP offer"""
        self.transaction_id += 1
        message = {
            "janus": "message",
            "transaction": str(self.transaction_id),
            "session_id": self.session_id,
            "handle_id": self.handle_id,
            "body": {
                "request": "configure",
                "audio": True,
                "video": False
            },
            "jsep": {
                "type": "offer",
                "sdp": offer.sdp
            }
        }
        
        await self.websocket.send(json.dumps(message))

    async def receive_answer(self):
        """接收SDP answer"""
        while True:
            response = await self.websocket.recv()
            data = json.loads(response)
            
            if "jsep" in data and data["jsep"]["type"] == "answer":
                return RTCSessionDescription(
                    sdp=data["jsep"]["sdp"],
                    type="answer"
                )
            
            # 处理其他消息类型
            if data.get("janus") == "event":
                logger.info(f"收到Janus事件: {data}")

    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
            logger.info("已关闭Janus连接")

class JanusWebRTCClient:
    """
    Janus WebRTC客户端 - 支持音频流传输
    """
    def __init__(self, janus_url: str = "ws://127.0.0.1:8001/janus-protocol", 
                 plugin: str = "janus.plugin.audiobridge",
                 room_id: int = 1234):
        self.janus_url = janus_url
        self.plugin = plugin
        self.room_id = room_id
        
        # WebRTC连接
        self.webrtc_connection: Optional[RTCPeerConnection] = None
        self.signaling: Optional[JanusSignaling] = None
        
        # 音频队列
        self.audio_queue = Queue()
        self.response_queue = Queue()
        
        # 音频轨道
        self.audio_receive_track: Optional[AudioReceiveTrack] = None
        self.audio_send_track: Optional[AudioSendTrack] = None
        
        # 状态标志
        self.connected = False
        self.running = False

    async def setup_webrtc_connection(self):
        """建立WebRTC连接"""
        try:
            # 创建RTCPeerConnection
            self.webrtc_connection = RTCPeerConnection()
            
            # 创建音频发送轨道并添加到连接
            self.audio_send_track = AudioSendTrack(self.response_queue)
            self.webrtc_connection.addTrack(self.audio_send_track)
            
            # 设置轨道处理器 - 处理接收到的音频轨道
            @self.webrtc_connection.on("track")
            def on_track(track):
                logger.info(f"收到轨道: {track.kind}")
                if track.kind == "audio":
                    logger.info("开始处理接收到的音频轨道")
                    # 创建音频接收轨道
                    self.audio_receive_track = AudioReceiveTrack(self.audio_queue)
                    # 启动音频轨道处理任务
                    asyncio.create_task(self.process_audio_track(track))
            
            # 设置连接状态监听器
            @self.webrtc_connection.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"WebRTC连接状态: {self.webrtc_connection.connectionState}")
                if self.webrtc_connection.connectionState == "failed":
                    logger.error("WebRTC连接失败，尝试重新连接")
                    await self.handle_webrtc_reconnect()
            
            # 创建Janus信令连接
            self.signaling = JanusSignaling(self.janus_url, self.plugin)
            if not await self.signaling.connect():
                logger.error("Janus信令连接失败")
                return False
            
            # 加入音频房间
            await self.signaling.join_room(self.room_id)
            
            # 创建offer
            offer = await self.webrtc_connection.createOffer()
            await self.webrtc_connection.setLocalDescription(offer)
            
            # 发送offer到Janus
            await self.signaling.send_offer(offer)
            
            # 接收answer
            answer = await self.signaling.receive_answer()
            if answer:
                await self.webrtc_connection.setRemoteDescription(answer)
                logger.info("WebRTC连接建立成功")
                self.connected = True
                return True
            else:
                logger.error("未收到Janus的answer")
                return False
            
        except Exception as e:
            logger.error(f"建立WebRTC连接失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def process_audio_track(self, track):
        """处理音频轨道"""
        try:
            while True:
                frame = await track.recv()
                if frame:
                    # 处理音频帧
                    if self.audio_receive_track:
                        await self.audio_receive_track.recv()
        except Exception as e:
            logger.error(f"音频轨道处理失败: {e}")

    async def handle_webrtc_reconnect(self):
        """处理WebRTC重连"""
        logger.info("开始WebRTC重连...")
        self.connected = False
        
        # 关闭现有连接
        if self.webrtc_connection:
            await self.webrtc_connection.close()
        
        if self.signaling:
            await self.signaling.close()
        
        # 等待一段时间后重连
        await asyncio.sleep(5)
        
        # 重新建立连接
        await self.setup_webrtc_connection()

    async def start(self):
        """启动WebRTC客户端"""
        logger.info("启动Janus WebRTC客户端...")
        
        # 建立WebRTC连接
        if not await self.setup_webrtc_connection():
            logger.error("WebRTC连接建立失败")
            return False
        
        self.running = True
        logger.info("Janus WebRTC客户端启动成功")
        return True

    async def stop(self):
        """停止WebRTC客户端"""
        logger.info("停止Janus WebRTC客户端...")
        
        self.running = False
        self.connected = False
        
        # 关闭WebRTC连接
        if self.webrtc_connection:
            await self.webrtc_connection.close()
        
        # 关闭信令连接
        if self.signaling:
            await self.signaling.close()
        
        logger.info("Janus WebRTC客户端已停止")

    def get_audio_data(self):
        """获取接收到的音频数据"""
        if not self.audio_queue.empty():
            return self.audio_queue.get()
        return None

    def send_audio_data(self, audio_data):
        """发送音频数据"""
        self.response_queue.put(audio_data)

    def is_connected(self):
        """检查连接状态"""
        return self.connected

async def main():
    """主函数"""
    print("Janus WebRTC Python客户端")
    print("用于与ESP32-S3语音助手通信（静态SRTP版本）")
    print("-" * 50)

    # 创建客户端
    client = JanusWebRTCClient(
        janus_url="ws://119.136.26.222:18001/janus-protocol",
        plugin="janus.plugin.audiobridge",
        room_id=1234
    )

    # 启动客户端
    success = await client.start()
    if not success:
        print("客户端启动失败！")
        return 1

    # 等待连接建立
    while not client.is_connected():
        await asyncio.sleep(1)

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))