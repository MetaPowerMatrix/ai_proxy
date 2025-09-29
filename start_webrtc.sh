#!/bin/bash

# AI音频处理客户端 - WebRTC版本启动脚本

echo "==================================="
echo "AI音频处理客户端 - WebRTC版本"
echo "==================================="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3"
    exit 1
fi

# 检查是否存在虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装WebRTC依赖..."
pip install -r requirements_webrtc.txt

# 设置环境变量
export JANUS_URL=${JANUS_URL:-"ws://127.0.0.1:8188"}
export AUDIO_DIR=${AUDIO_DIR:-"audio_files"}
export PROCESSED_DIR=${PROCESSED_DIR:-"processed_files"}

echo "环境配置:"
echo "  Janus URL: $JANUS_URL"
echo "  音频目录: $AUDIO_DIR"
echo "  处理目录: $PROCESSED_DIR"
echo ""

# 启动参数
VOICE_CATEGORY=${VOICE_CATEGORY:-"御姐配音暧昧"}
USE_MINICPM=${USE_MINICPM:-false}
USE_F5TTS=${USE_F5TTS:-false}
SKIP_TTS=${SKIP_TTS:-false}
USE_UNCENSORED=${USE_UNCENSORED:-false}

# 构建启动命令
CMD="python3 ai_client_webrtc.py --voice-category \"$VOICE_CATEGORY\""

if [ "$USE_MINICPM" = "true" ]; then
    CMD="$CMD --use-minicpm"
fi

if [ "$USE_F5TTS" = "true" ]; then
    CMD="$CMD --use-f5tts"
fi

if [ "$SKIP_TTS" = "true" ]; then
    CMD="$CMD --skip-tts"
fi

if [ "$USE_UNCENSORED" = "true" ]; then
    CMD="$CMD --use-uncensored"
fi

echo "启动命令: $CMD"
echo ""

# 启动程序
echo "启动AI音频处理客户端..."
eval $CMD
