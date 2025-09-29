# AI音频处理客户端 - WebRTC版本

本版本将原有的WebSocket音频传输方式替换为WebRTC，通过Janus网关接收设备音频数据，并将AI模型的音频回复通过Janus转发回设备播放。

## 主要变更

### 1. 架构变更
- **原版本**: WebSocket直接传输音频二进制数据
- **WebRTC版本**: 通过Janus WebRTC网关进行音频流传输

### 2. 新增依赖
```bash
pip install -r requirements_webrtc.txt
```

主要新增依赖包括：
- `aiortc>=1.6.0` - WebRTC客户端库
- `websockets>=11.0` - Janus信令通信
- `av>=10.0.0` - 音频/视频处理

### 3. 配置变更

新增环境变量：
```bash
# Janus WebRTC网关配置
JANUS_URL=ws://127.0.0.1:8188          # Janus WebSocket信令地址
JANUS_API_SECRET=janusrocks            # Janus API密钥（可选）
```

### 4. 功能特点

#### WebRTC音频处理流程
1. **建立连接**: 通过Janus信令建立WebRTC连接
2. **音频接收**: 通过WebRTC音频轨道接收设备音频
3. **音频缓冲**: 将接收到的音频帧缓冲至指定大小后处理
4. **AI处理**: 语音识别 → AI对话 → 语音合成
5. **音频发送**: 通过WebRTC音频轨道发送AI回复音频

#### 核心组件

**AudioReceiveTrack**: 
- 接收来自Janus的音频轨道
- 处理多声道转单声道
- 音频格式转换和缓冲管理

**AudioSendTrack**:
- 向Janus发送音频轨道
- 支持分帧发送和静音填充
- 音频流连续播放管理

**JanusSignaling**:
- 处理Janus WebRTC信令
- 会话和插件管理
- SDP协商和ICE处理

## 使用方法

### 1. 启动Janus网关
确保Janus WebRTC网关已启动并配置了audiobridge插件：

```bash
# 示例Janus配置
# 确保audiobridge插件已启用
# 创建音频房间ID: 1234
```

### 2. 运行WebRTC客户端
```bash
python ai_client_webrtc.py --voice-category "御姐配音暧昧"
```

支持的参数：
- `--use-minicpm`: 使用MiniCPM大模型
- `--skip-tts`: 跳过文本转语音
- `--use-f5tts`: 使用F5-TTS引擎
- `--use-uncensored`: 使用不审查聊天接口
- `--voice-category`: 指定音色名称

### 3. 设备端连接
设备端需要连接到同一个Janus音频房间（默认房间ID: 1234）进行音频通信。

## 技术细节

### 音频格式
- 采样率: 16kHz
- 位深度: 16位
- 声道: 单声道
- 帧长度: 20ms (320样本)

### 缓冲策略
- 接收缓冲: 1秒音频数据 (32KB)
- 发送分帧: 20ms帧，支持连续播放
- 队列管理: 异步音频处理队列

### 错误处理
- 自动重连机制
- 连接状态监控
- 异常恢复和资源清理

## 故障排除

### 常见问题

1. **Janus连接失败**
   - 检查Janus服务是否运行
   - 确认WebSocket地址和端口
   - 检查audiobridge插件是否启用

2. **音频质量问题**
   - 调整缓冲区大小
   - 检查网络延迟和丢包
   - 确认音频编解码器配置

3. **依赖安装问题**
   - 确保安装了所有WebRTC相关依赖
   - 检查系统音频库支持
   - 更新pip和相关包版本

### 日志调试
程序提供详细的日志输出，包括：
- WebRTC连接状态
- 音频数据流量统计
- Janus信令交互
- 音频处理性能指标

## 性能优化

1. **网络优化**
   - 使用低延迟网络配置
   - 调整WebRTC带宽限制
   - 启用音频回声消除

2. **音频优化**
   - 调整音频缓冲区大小
   - 优化音频处理线程
   - 使用硬件音频加速

3. **资源管理**
   - 监控内存使用情况
   - 及时清理音频缓冲
   - 优化异步任务调度

## 与原版本对比

| 特性 | WebSocket版本 | WebRTC版本 |
|------|---------------|------------|
| 传输协议 | WebSocket | WebRTC |
| 音频质量 | 较好 | 优秀 |
| 网络适应性 | 一般 | 强 |
| NAT穿透 | 需要配置 | 自动处理 |
| 延迟 | 中等 | 低 |
| 可扩展性 | 有限 | 强 |
| 部署复杂度 | 简单 | 中等 |

WebRTC版本在音频质量、网络适应性和扩展性方面有显著优势，适合生产环境部署。
