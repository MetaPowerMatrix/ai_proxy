#!/usr/bin/env python3
"""
Janus WebRTC Python客户端
用于与ESP32-S3语音助手进行音频通信（静态SRTP版本）

功能：
1. 通过Janus Gateway连接到ESP32-S3
2. 发送和接收Opus音频数据
3. 支持静态SRTP密钥配置
4. 实时音频播放和录制

依赖：
pip install requests websockets pyaudio opus-python cryptography

作者：Claude Code
"""

import asyncio
import json
import logging
import struct
import time
import threading
from typing import Optional, Dict, Any
import socket
import hashlib
import hmac

import requests
import pyaudio
import opus

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class JanusClient:
    """Janus WebRTC Gateway客户端"""

    def __init__(self, server_url: str = "http://119.136.26.222:8088",
                 admin_key: str = "janusoverlord"):
        self.server_url = server_url.rstrip('/')
        self.admin_key = admin_key
        self.session_id: Optional[int] = None
        self.handle_id: Optional[int] = None
        self.plugin_name = "janus.plugin.echotest"

        # 音频配置
        self.sample_rate = 16000
        self.channels = 1
        self.frame_duration = 20  # ms
        self.opus_frame_size = int(self.sample_rate * self.frame_duration / 1000)

        # SRTP配置（与ESP32端保持一致）
        self.static_srtp_key = bytes([
            # Master Key (16 bytes)
            0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF,
            0xFE, 0xDC, 0xBA, 0x98, 0x76, 0x54, 0x32, 0x10,
            # Master Salt (14 bytes)
            0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08,
            0x07, 0x06, 0x05, 0x04, 0x03, 0x02
        ])

        # RTP配置
        self.ssrc = 0x87654321  # 与ESP32不同的SSRC
        self.sequence_number = 1000
        self.timestamp = int(time.time() * self.sample_rate) & 0xFFFFFFFF

        # UDP套接字
        self.rtp_socket: Optional[socket.socket] = None
        self.esp32_address: Optional[tuple] = None

        # Opus编解码器
        self.opus_encoder = opus.Encoder(self.sample_rate, self.channels, opus.APPLICATION_VOIP)
        self.opus_decoder = opus.Decoder(self.sample_rate, self.channels)

        # PyAudio
        self.audio = pyaudio.PyAudio()
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None

        # 控制标志
        self.running = False
        self.connected = False

    def create_session(self) -> bool:
        """创建Janus会话"""
        try:
            url = f"{self.server_url}/janus"
            data = {
                "janus": "create",
                "transaction": self._generate_transaction_id()
            }

            logger.info("创建Janus会话...")
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("janus") == "success":
                self.session_id = result["data"]["id"]
                logger.info(f"会话创建成功, ID: {self.session_id}")
                return True
            else:
                logger.error(f"会话创建失败: {result}")
                return False

        except Exception as e:
            logger.error(f"创建会话异常: {e}")
            return False

    def attach_plugin(self) -> bool:
        """附加到EchoTest插件"""
        try:
            url = f"{self.server_url}/janus/{self.session_id}"
            data = {
                "janus": "attach",
                "plugin": self.plugin_name,
                "transaction": self._generate_transaction_id()
            }

            logger.info(f"附加插件: {self.plugin_name}")
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("janus") == "success":
                self.handle_id = result["data"]["id"]
                logger.info(f"插件附加成功, Handle ID: {self.handle_id}")
                return True
            else:
                logger.error(f"插件附加失败: {result}")
                return False

        except Exception as e:
            logger.error(f"附加插件异常: {e}")
            return False

    def send_offer(self) -> bool:
        """发送WebRTC Offer"""
        try:
            # 创建SDP Offer（静态SRTP版本）
            sdp_offer = self._create_sdp_offer()

            url = f"{self.server_url}/janus/{self.session_id}/{self.handle_id}"
            data = {
                "janus": "message",
                "transaction": self._generate_transaction_id(),
                "body": {
                    "request": "configure",
                    "audio": True,
                    "video": False
                },
                "jsep": {
                    "type": "offer",
                    "sdp": sdp_offer
                }
            }

            logger.info("发送WebRTC Offer...")
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            result = response.json()
            logger.info(f"Offer响应: {result}")

            # 解析answer SDP获取远端信息
            if "jsep" in result and result["jsep"]["type"] == "answer":
                self._parse_answer_sdp(result["jsep"]["sdp"])
                return True
            else:
                logger.error("未收到SDP Answer")
                return False

        except Exception as e:
            logger.error(f"发送Offer异常: {e}")
            return False

    def _create_sdp_offer(self) -> str:
        """创建SDP Offer（支持静态SRTP）"""
        import base64

        # 将静态SRTP密钥编码为base64
        key_base64 = base64.b64encode(self.static_srtp_key).decode()

        sdp = f"""v=0
o=janus 123456789 2 IN IP4 127.0.0.1
s=Janus Python Client
t=0 0
a=group:BUNDLE 0
a=msid-semantic: WMS janus
m=audio 9 RTP/SAVPF 111
c=IN IP4 0.0.0.0
a=rtcp:9 IN IP4 0.0.0.0
a=mid:0
a=sendrecv
a=rtcp-mux
a=rtpmap:111 opus/48000/2
a=rtcp-fb:111 transport-cc
a=fmtp:111 minptime=10;useinbandfec=1
a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:{key_base64}
a=ssrc:{self.ssrc} cname:janus-python-client
a=ssrc:{self.ssrc} msid:janus audio0
a=ssrc:{self.ssrc} mslabel:janus
a=ssrc:{self.ssrc} label:audio0
"""

        return sdp.replace('\n', '\r\n')

    def _parse_answer_sdp(self, sdp: str) -> None:
        """解析Answer SDP获取远端RTP信息"""
        lines = sdp.split('\r\n')

        for line in lines:
            # 查找连接信息
            if line.startswith('c=IN IP4'):
                ip = line.split()[-1]
                if ip != '0.0.0.0':
                    logger.info(f"远端IP: {ip}")

            # 查找音频端口
            elif line.startswith('m=audio'):
                parts = line.split()
                if len(parts) >= 2:
                    port = int(parts[1])
                    logger.info(f"远端RTP端口: {port}")
                    # 设置ESP32地址（假设与Janus在同一服务器）
                    server_ip = self.server_url.split('://')[1].split(':')[0]
                    self.esp32_address = (server_ip, 10000)  # ESP32固定使用10000端口

    def setup_rtp_socket(self) -> bool:
        """设置RTP UDP套接字"""
        try:
            self.rtp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_socket.bind(('0.0.0.0', 0))  # 绑定任意可用端口

            local_port = self.rtp_socket.getsockname()[1]
            logger.info(f"RTP套接字绑定到端口: {local_port}")
            return True

        except Exception as e:
            logger.error(f"RTP套接字设置失败: {e}")
            return False

    def setup_audio(self) -> bool:
        """设置音频输入输出"""
        try:
            # 输入流（麦克风）
            self.input_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.opus_frame_size
            )

            # 输出流（扬声器）
            self.output_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.opus_frame_size
            )

            logger.info("音频设备初始化成功")
            return True

        except Exception as e:
            logger.error(f"音频设备初始化失败: {e}")
            return False

    def create_rtp_packet(self, opus_data: bytes) -> bytes:
        """创建RTP数据包"""
        # RTP头结构: V(2)|P(1)|X(1)|CC(4)|M(1)|PT(7)|序列号(16)|时间戳(32)|SSRC(32)
        version = 2
        padding = 0
        extension = 0
        csrc_count = 0
        marker = 0
        payload_type = 111  # Opus

        # 构建RTP头
        byte0 = (version << 6) | (padding << 5) | (extension << 4) | csrc_count
        byte1 = (marker << 7) | payload_type

        rtp_header = struct.pack('!BBHLL',
                                byte0, byte1,
                                self.sequence_number,
                                self.timestamp,
                                self.ssrc)

        # 更新序列号和时间戳
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        self.timestamp = (self.timestamp + self.opus_frame_size) & 0xFFFFFFFF

        return rtp_header + opus_data

    def encrypt_srtp_packet(self, rtp_packet: bytes) -> bytes:
        """使用静态密钥加密SRTP包（简化实现）"""
        # 注意：这是一个简化的SRTP实现，生产环境应该使用专业的SRTP库
        # 这里只是为了演示与ESP32的兼容性

        # 提取master key和salt
        master_key = self.static_srtp_key[:16]
        master_salt = self.static_srtp_key[16:]

        # 简化的AES-CM加密（实际应该使用标准SRTP实现）
        # 这里仅做示例，实际部署请使用libsrtp
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        # 构建IV（简化版本）
        iv = master_salt[:12] + b'\x00\x00\x00\x00'

        # AES-CTR加密RTP载荷（跳过RTP头）
        cipher = Cipher(algorithms.AES(master_key), modes.CTR(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        rtp_header = rtp_packet[:12]
        rtp_payload = rtp_packet[12:]
        encrypted_payload = encryptor.update(rtp_payload) + encryptor.finalize()

        # 计算HMAC认证标签（简化）
        auth_tag = hmac.new(master_key, rtp_header + encrypted_payload, hashlib.sha1).digest()[:10]

        return rtp_header + encrypted_payload + auth_tag

    def send_audio_loop(self):
        """音频发送循环"""
        logger.info("开始音频发送循环...")

        while self.running:
            try:
                # 从麦克风读取音频数据
                if self.input_stream and not self.input_stream.is_stopped():
                    audio_data = self.input_stream.read(self.opus_frame_size, exception_on_overflow=False)

                    # 转换为16位整数数组
                    audio_samples = struct.unpack(f'<{self.opus_frame_size}h', audio_data)

                    # Opus编码
                    opus_data = self.opus_encoder.encode(audio_samples, self.opus_frame_size)

                    # 创建RTP包
                    rtp_packet = self.create_rtp_packet(opus_data)

                    # SRTP加密
                    srtp_packet = self.encrypt_srtp_packet(rtp_packet)

                    # 发送到ESP32
                    if self.esp32_address and self.rtp_socket:
                        self.rtp_socket.sendto(srtp_packet, self.esp32_address)

                else:
                    time.sleep(0.02)  # 20ms

            except Exception as e:
                logger.error(f"音频发送异常: {e}")
                time.sleep(0.1)

    def receive_audio_loop(self):
        """音频接收循环"""
        logger.info("开始音频接收循环...")

        if not self.rtp_socket:
            logger.error("RTP套接字未初始化")
            return

        self.rtp_socket.settimeout(1.0)  # 1秒超时

        while self.running:
            try:
                # 接收SRTP数据包
                data, addr = self.rtp_socket.recvfrom(1500)

                if len(data) < 12:  # RTP头最小长度
                    continue

                logger.debug(f"收到来自{addr}的SRTP包: {len(data)}字节")

                # 解密SRTP包（简化实现）
                rtp_packet = self.decrypt_srtp_packet(data)
                if not rtp_packet:
                    continue

                # 解析RTP头
                if len(rtp_packet) < 12:
                    continue

                rtp_header = rtp_packet[:12]
                opus_data = rtp_packet[12:]

                # 解析RTP头信息
                byte0, byte1, seq, ts, ssrc = struct.unpack('!BBHLL', rtp_header)
                payload_type = byte1 & 0x7F

                if payload_type == 111 and len(opus_data) > 0:  # Opus数据
                    try:
                        # Opus解码
                        pcm_data = self.opus_decoder.decode(opus_data, self.opus_frame_size)

                        # 转换为字节数组
                        audio_bytes = struct.pack(f'<{len(pcm_data)}h', *pcm_data)

                        # 播放音频
                        if self.output_stream and not self.output_stream.is_stopped():
                            self.output_stream.write(audio_bytes)

                    except Exception as e:
                        logger.debug(f"Opus解码失败: {e}")

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"音频接收异常: {e}")
                time.sleep(0.1)

    def decrypt_srtp_packet(self, srtp_packet: bytes) -> Optional[bytes]:
        """解密SRTP数据包（简化实现）"""
        try:
            if len(srtp_packet) < 22:  # RTP头+认证标签最小长度
                return None

            # 分离认证标签
            auth_tag = srtp_packet[-10:]
            encrypted_packet = srtp_packet[:-10]

            # 验证HMAC（简化）
            master_key = self.static_srtp_key[:16]
            expected_tag = hmac.new(master_key, encrypted_packet, hashlib.sha1).digest()[:10]

            if auth_tag != expected_tag:
                logger.debug("SRTP认证失败")
                return None

            # 解密载荷
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend

            master_salt = self.static_srtp_key[16:]
            iv = master_salt[:12] + b'\x00\x00\x00\x00'

            cipher = Cipher(algorithms.AES(master_key), modes.CTR(iv), backend=default_backend())
            decryptor = cipher.decryptor()

            rtp_header = encrypted_packet[:12]
            encrypted_payload = encrypted_packet[12:]
            decrypted_payload = decryptor.update(encrypted_payload) + decryptor.finalize()

            return rtp_header + decrypted_payload

        except Exception as e:
            logger.debug(f"SRTP解密失败: {e}")
            return None

    def start(self) -> bool:
        """启动客户端"""
        logger.info("启动Janus Python客户端...")

        # 1. 创建会话
        if not self.create_session():
            return False

        # 2. 附加插件
        if not self.attach_plugin():
            return False

        # 3. 发送Offer
        if not self.send_offer():
            return False

        # 4. 设置RTP套接字
        if not self.setup_rtp_socket():
            return False

        # 5. 设置音频设备
        if not self.setup_audio():
            return False

        # 6. 启动音频处理线程
        self.running = True
        self.connected = True

        send_thread = threading.Thread(target=self.send_audio_loop, daemon=True)
        receive_thread = threading.Thread(target=self.receive_audio_loop, daemon=True)

        send_thread.start()
        receive_thread.start()

        logger.info("Janus客户端启动成功！")
        logger.info(f"与ESP32通信地址: {self.esp32_address}")
        logger.info("按Ctrl+C停止...")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("用户中断，正在停止...")
            self.stop()

        return True

    def stop(self):
        """停止客户端"""
        logger.info("停止Janus客户端...")

        self.running = False
        self.connected = False

        # 关闭音频流
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()

        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()

        # 关闭音频系统
        if self.audio:
            self.audio.terminate()

        # 关闭RTP套接字
        if self.rtp_socket:
            self.rtp_socket.close()

        logger.info("客户端已停止")

    def _generate_transaction_id(self) -> str:
        """生成事务ID"""
        import random
        import string
        return ''.join(random.choices(string.ascii_letters + string.digits, k=12))

def main():
    """主函数"""
    print("Janus WebRTC Python客户端")
    print("用于与ESP32-S3语音助手通信（静态SRTP版本）")
    print("-" * 50)

    # 创建客户端
    client = JanusClient(
        server_url="http://119.136.26.222:8088",
        admin_key="janusoverlord"
    )

    # 启动客户端
    success = client.start()

    if not success:
        print("客户端启动失败！")
        return 1

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())