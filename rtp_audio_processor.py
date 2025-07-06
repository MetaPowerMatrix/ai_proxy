import asyncio
import socket
import struct
import logging
import time
from collections import deque
from typing import Deque

import numpy as np
import websockets

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s: %(message)s')

# ===================== 配置参数 ===================== #
INPUT_PORT = 5004               # 本地监听的 RTP 端口（接收设备音频）
OUTPUT_IP = '127.0.0.1'         # 设备的 IP 地址（发送处理后音频）
OUTPUT_PORT = 5006              # 发送 RTP 的端口
WS_URI = 'ws://localhost:8000/audio_chat'  # 大模型聊天服务的 WebSocket 地址

SAMPLE_RATE = 16000             # 采样率 Hz
FRAME_DURATION = 0.02           # 每帧时长 20ms
SAMPLES_PER_FRAME = int(SAMPLE_RATE * FRAME_DURATION)
BYTES_PER_SAMPLE = 2            # int16 PCM
BYTES_PER_FRAME = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE

PAYLOAD_TYPE = 96               # RTP PayloadType (96 ~ 127 动态类型)
SSRC = 0x12345678               # 固定 SSRC

SILENCE_THRESHOLD = 500         # 判定静默的平均幅度阈值
SILENCE_DURATION = 3.0          # 连续静默秒数
# ================================================== #


def parse_rtp_payload(packet: bytes) -> bytes:
    """提取 RTP 负载（假设无扩展、CSRC 等）。"""
    if len(packet) < 12:
        return b''
    return packet[12:]


def build_rtp_packet(payload: bytes, seq: int, timestamp: int, payload_type: int = PAYLOAD_TYPE, marker: int = 0) -> bytes:
    """构造最简 RTP 包（无扩展、无 CSRC）。"""
    v = 2  # RTP version
    p = 0  # no padding
    x = 0  # no extension
    cc = 0  # CSRC count
    b1 = (v << 6) | (p << 5) | (x << 4) | cc
    b2 = (marker << 7) | (payload_type & 0x7F)
    header = struct.pack('!BBHII', b1, b2, seq & 0xFFFF, timestamp & 0xFFFFFFFF, SSRC)
    return header + payload


def frame_is_silent(frame: bytes) -> bool:
    """判断单帧是否为静默（平均绝对幅度低于阈值）。"""
    if len(frame) < BYTES_PER_FRAME:
        # 不完整帧按静默处理
        return True
    pcm = np.frombuffer(frame, dtype=np.int16)
    return np.abs(pcm).mean() < SILENCE_THRESHOLD


async def rtp_receiver(sock: socket.socket, frame_queue: asyncio.Queue):
    """从 UDP Socket 接收 RTP 包，提取音频负载后放入队列。"""
    loop = asyncio.get_running_loop()
    while True:
        data, _addr = await loop.sock_recvfrom(sock, 4096)
        payload = parse_rtp_payload(data)
        if payload:
            await frame_queue.put(payload)


async def rtp_sender(sock: socket.socket, frame_queue: asyncio.Queue, dst):
    """把队列中的音频帧组装为 RTP 包后发送给设备。"""
    loop = asyncio.get_running_loop()
    seq = 0
    timestamp = 0
    while True:
        frame = await frame_queue.get()
        # 若帧长度不足 BYTES_PER_FRAME，进行 0 填充
        if len(frame) < BYTES_PER_FRAME:
            frame += b'\x00' * (BYTES_PER_FRAME - len(frame))
        packet = build_rtp_packet(frame, seq, timestamp)
        await loop.sock_sendto(sock, packet, dst)
        seq = (seq + 1) % 0x10000
        timestamp = (timestamp + SAMPLES_PER_FRAME) % 0xFFFFFFFF


async def query_llm_via_ws(audio_bytes: bytes) -> bytes:
    """通过 WebSocket 调用大模型，把音频发送过去并获取返回音频。"""
    logging.info('连接大模型 WebSocket 服务...')
    async with websockets.connect(WS_URI, max_size=None) as ws:
        await ws.send(audio_bytes)
        logging.info('已发送 %d 字节音频，等待回复...', len(audio_bytes))
        resp = await ws.recv()
        if isinstance(resp, str):
            resp = resp.encode()
        logging.info('收到回复音频 %d 字节', len(resp))
        return resp


async def silence_detector_processor(in_queue: asyncio.Queue, out_queue: asyncio.Queue):
    """检测静默，当静默超过阈值后把缓冲音频发送到大模型服务，返回结果写入发送队列。"""
    buffer: Deque[bytes] = deque()
    silent_time = 0.0
    last_check = time.time()

    while True:
        frame = await in_queue.get()
        buffer.append(frame)

        now = time.time()
        elapsed = now - last_check
        last_check = now

        # 根据当前帧是否静默更新静默计时
        if frame_is_silent(frame):
            silent_time += FRAME_DURATION
        else:
            silent_time = 0.0

        # 若静默时间超过阈值，触发发送
        if silent_time >= SILENCE_DURATION and buffer:
            audio_bytes = b''.join(buffer)
            buffer.clear()
            silent_time = 0.0

            logging.info('检测到 %.1f 秒静默，向大模型发送 %d 字节音频', SILENCE_DURATION, len(audio_bytes))
            try:
                resp_audio = await query_llm_via_ws(audio_bytes)
                # 把返回音频切成帧加入 out_queue
                for i in range(0, len(resp_audio), BYTES_PER_FRAME):
                    await out_queue.put(resp_audio[i:i + BYTES_PER_FRAME])
            except Exception as e:
                logging.error('WebSocket 调用失败: %s', e)


async def main():
    """主函数：启动所有协程任务。"""
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind(('0.0.0.0', INPUT_PORT))
    recv_sock.setblocking(False)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.setblocking(False)

    frame_in_queue: asyncio.Queue = asyncio.Queue()
    frame_out_queue: asyncio.Queue = asyncio.Queue()

    tasks = [
        asyncio.create_task(rtp_receiver(recv_sock, frame_in_queue)),
        asyncio.create_task(silence_detector_processor(frame_in_queue, frame_out_queue)),
        asyncio.create_task(rtp_sender(send_sock, frame_out_queue, (OUTPUT_IP, OUTPUT_PORT)))
    ]

    logging.info('RTP 接收端口 %d，发送到 %s:%d，WebSocket: %s', INPUT_PORT, OUTPUT_IP, OUTPUT_PORT, WS_URI)
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('退出程序') 