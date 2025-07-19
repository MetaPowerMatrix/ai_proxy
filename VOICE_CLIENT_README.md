 # MiniCPM-o Python语音客户端

这是一个仿照前端VoiceCall_0105.vue实现的Python语音对话客户端，用于与MiniCPM-o-2.6后端服务进行实时语音对话。

## 功能特性

- 实时音频录制和流式传输
- WebSocket实时音频上传
- SSE流式接收模型响应
- 实时音频播放
- 支持配置自定义参数

## 安装依赖

```bash
pip install -r requirements_voice_client.txt
```

### 系统依赖

**macOS:**
```bash
brew install portaudio
```

**Ubuntu/Debian:**
```bash
sudo apt-get install portaudio19-dev python3-pyaudio
```

**Windows:**
PyAudio通常需要从预编译的wheel安装：
```bash
pip install pipwin
pipwin install pyaudio
```

## 使用方法

### 基本使用

```bash
python voice_client.py
```

### 自定义参数

```bash
# 指定服务器地址和端口
python voice_client.py --host 192.168.1.100 --port 32550

# 设置通话时长（秒）
python voice_client.py --duration 60
```

### 参数说明

- `--host`: 后端服务器地址 (默认: 127.0.0.1)
- `--port`: 后端服务器端口 (默认: 32550)
- `--duration`: 通话时长，秒 (默认: 30)

## 工作原理

1. **初始化**: 上传用户配置到后端
2. **双向通信**:
   - WebSocket连接: 实时发送1秒音频片段
   - SSE连接: 接收模型的文本和音频响应
3. **音频处理**:
   - 录制: 16kHz采样率，单声道
   - 编码: WAV格式，Base64传输
   - 播放: 实时播放返回的音频

## 技术架构

```
录音线程 -> 音频队列 -> WebSocket发送 -> 后端模型
                                           ↓
播放线程 <- 播放队列 <- SSE接收 <- 模型响应
```

## 注意事项

1. 确保后端model_server.py已启动
2. 需要麦克风和扬声器权限
3. 建议在安静环境下使用
4. 按Ctrl+C可提前结束通话

## 故障排除

### 音频设备问题
```python
# 列出可用音频设备
import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"{i}: {info['name']}")
```

### WebSocket连接失败
- 检查后端服务是否启动
- 确认端口号是否正确
- 检查防火墙设置

### 音频质量问题
- 确保麦克风正常工作
- 调整系统音量设置
- 检查网络延迟