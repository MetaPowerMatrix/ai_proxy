#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MiniCPM流式数据处理
"""

import sys
import os
from minicpm_client import MiniCPMClient


def test_stream_processing():
    """测试流式音频处理"""
    print("=" * 50)
    print("测试MiniCPM流式音频处理")
    print("=" * 50)
    
    # 创建客户端
    client = MiniCPMClient()
    
    # 1. 检查服务状态
    print("1️⃣ 检查服务状态...")
    status = client.check_service_status()
    if not status or status.status_code != 200:
        print("❌ MiniCPM服务不可用")
        return False
    
    print("✅ MiniCPM服务正常")
    
    # 2. 检查音频文件
    test_audio_files = [
        "test_audio.wav",
        "../test_audio.wav", 
        "audio_files/test_audio.wav",
        "/data/test_audio.wav"
    ]
    
    audio_file = None
    for file_path in test_audio_files:
        if os.path.exists(file_path):
            audio_file = file_path
            break
    
    if not audio_file:
        print("⚠️  未找到测试音频文件")
        print("请创建一个名为 test_audio.wav 的音频文件进行测试")
        return False
    
    print(f"📁 使用音频文件: {audio_file}")
    
    # 3. 测试流式处理
    print("3️⃣ 开始流式音频处理测试...")
    try:
        audio_chunks, text_response = client.stream_audio_processing(audio_file)
        
        print("\n📊 处理结果:")
        print(f"   文本回复: {text_response}")
        print(f"   音频片段数量: {len(audio_chunks) if audio_chunks else 0}")
        
        if audio_chunks:
            total_audio_size = sum(len(chunk[0]) if chunk[0] is not None else 0 for chunk in audio_chunks)
            print(f"   总音频大小: {total_audio_size} 字节")
        
        if text_response or audio_chunks:
            print("✅ 流式处理成功！")
            return True
        else:
            print("⚠️  流式处理完成，但没有收到有效回复")
            return False
            
    except Exception as e:
        print(f"❌ 流式处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_stream_processing()
    
    if not success:
        print("\n💡 故障排除建议:")
        print("   1. 确保MiniCPM服务正在运行")
        print("   2. 检查网络连接") 
        print("   3. 查看详细的错误日志")
    else:
        print("\n🎉 所有测试通过！") 