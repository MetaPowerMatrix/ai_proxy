# 音频代理功能使用说明

## 概述

VoiceClient现在支持音频代理模式，可以从外部WebSocket接收音频数据，转发给大模型服务端，并将AI回复的音频数据转发回外部WebSocket。这个功能特别适合构建音频处理中间件或集成到现有的音频处理系统中。

## 新增功能

### 1. start_audio_proxy 方法

这是核心的音频代理方法，包含以下功能：

- **音频接收**: 从外部WebSocket持续接收PCM音频数据
- **格式转换**: 将PCM数据转换为大模型需要的WAV base64格式
- **智能缓冲**: 累积音频数据到1秒后再发送，提高处理效率
- **双向转发**: 将AI回复的音频和文本数据转发回外部WebSocket

### 2. 相关辅助方法

- `external_audio_receiver()`: 处理外部WebSocket音频数据接收
- `websocket_sender_proxy()`: 发送音频数据到大模型WebSocket
- `sse_receiver_proxy()`: 接收大模型的SSE响应
- `handle_sse_message_proxy()`: 处理并转发AI回复

## 使用方法

### 基本用法

```python
from voice_client import VoiceClient
import asyncio

async def main():
    # 创建VoiceClient实例
    client = VoiceClient(server_host="127.0.0.1", server_port=32550)
    
    # 假设你有一个外部WebSocket连接
    external_websocket = await get_external_websocket()
    
    # 配置数据（可选）
    config_data = {
        "assistantPrompt": "You are a helpful AI assistant.",
        "audioFormat": "wav",
        "vadThreshold": 0.5
    }
    
    # 启动音频代理
    await client.start_audio_proxy(external_websocket, config_data)

if __name__ == "__main__":
    asyncio.run(main())
```

### 作为FastAPI服务

```python
from fastapi import FastAPI, WebSocket
from voice_client import VoiceClient

app = FastAPI()

@app.websocket("/audio_proxy")
async def audio_proxy_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    voice_client = VoiceClient()
    
    try:
        await voice_client.start_audio_proxy(websocket)
    finally:
        await voice_client.http_client.aclose()

# 运行: uvicorn your_app:app --host 0.0.0.0 --port 8001
```

## 数据格式

### 输入音频格式
- **格式**: PCM 16位
- **采样率**: 16000 Hz
- **声道**: 单声道
- **传输**: WebSocket二进制数据

### 输出数据格式

#### 文本回复
```json
{
    "type": "text",
    "content": "AI的文本回复内容"
}
```

#### 音频回复
- **格式**: PCM 16位二进制数据
- **采样率**: 16000 Hz
- **传输**: WebSocket二进制数据

## 示例文件

### 1. audio_proxy_example.py
完整的FastAPI服务器示例，演示如何集成音频代理功能到Web服务中。

**运行方法:**
```bash
cd ai_proxy
python audio_proxy_example.py
```
或
```bash
uvicorn audio_proxy_example:app --host 0.0.0.0 --port 8001
```

### 2. test_audio_proxy.py
测试客户端，可以生成测试音频或使用麦克风来测试代理功能。

**运行方法:**
```bash
# 使用生成的测试音频
python test_audio_proxy.py --mode generated

# 使用麦克风录音测试
python test_audio_proxy.py --mode microphone

# 指定代理服务器地址
python test_audio_proxy.py --proxy-url ws://localhost:8001/audio_proxy
```

## 依赖要求

确保安装以下Python包：

```bash
pip install fastapi uvicorn websockets pyaudio numpy wave
```

对于现有的VoiceClient依赖：
```bash
pip install httpx sseclient
```

## 典型使用场景

1. **音频处理中间件**: 在现有音频系统和AI服务之间提供代理层
2. **实时语音对话**: 构建实时语音对话应用
3. **音频流处理**: 处理连续的音频流数据
4. **多客户端支持**: 支持多个客户端同时连接的音频服务

## 注意事项

1. **音频格式**: 确保输入音频为16位PCM格式，16000Hz采样率
2. **网络延迟**: 实时音频传输对网络延迟敏感，建议在低延迟网络环境下使用
3. **资源管理**: 记得在使用完毕后关闭WebSocket连接和释放资源
4. **错误处理**: 实现适当的错误处理机制以应对网络中断等情况

## 性能优化

1. **缓冲策略**: 默认累积1秒音频再发送，可根据需要调整`chunk_duration`
2. **并发处理**: 音频接收、发送和播放使用异步并发处理
3. **内存管理**: 及时清理音频缓冲区避免内存泄漏

## 故障排除

### 常见问题

1. **连接失败**: 检查大模型服务是否正常运行
2. **音频格式错误**: 确认PCM格式和采样率设置正确
3. **延迟过高**: 检查网络连接和缓冲区设置
4. **内存占用高**: 检查音频缓冲区是否正常清理

### 调试建议

1. 启用详细日志: `logging.basicConfig(level=logging.DEBUG)`
2. 监控WebSocket连接状态
3. 检查音频数据大小和格式
4. 验证大模型服务响应 