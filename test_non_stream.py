#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCPM 非流式音频处理测试
作为流式处理的备选方案
"""

import os
import time
import requests
from minicpm_client import MiniCPMClient


def test_non_stream_audio():
    """测试非流式的音频处理"""
    
    print("=" * 60)
    print("MiniCPM 非流式音频处理测试")
    print("=" * 60)
    
    # 检查音频文件
    if not os.path.exists("test_audio.wav"):
        print("❌ 测试音频文件不存在")
        return
    
    client = MiniCPMClient()
    
    # 1. 健康检查
    print("1️⃣ 检查服务状态...")
    if not client.check_service_status:
        print("❌ MiniCPM服务不可用")
        return
    print("✅ MiniCPM服务正常")
    
    # 2. 加载音频
    try:
        audio_base64 = client.load_audio_file("test_audio.wav")
        print(f"📁 音频文件加载成功: {len(audio_base64)} 字符")
    except Exception as e:
        print(f"❌ 音频文件加载失败: {e}")
        return
    
    # 3. 发送stream请求
    print("3️⃣ 发送音频流请求...")
    try:
        stream_data = {
            "messages": [{
                "role": "user", 
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_base64,
                        "format": "wav",
                        "timestamp": str(int(time.time() * 1000))
                    }
                }]
            }]
        }
        
        headers = {"uid": client.uid, "Content-Type": "application/json"}
        response = requests.post(
            f"{client.base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=180  # 3分钟
        )
        
        print(f"Stream响应: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Stream请求失败: {response.text}")
            return
            
    except Exception as e:
        print(f"❌ Stream请求异常: {e}")
        return
    
    # 4. 发送非流式completions请求
    print("4️⃣ 发送非流式completions请求...")
    try:
        headers = {"uid": client.uid}  # 不设置Accept: text/event-stream
        
        start_time = time.time()
        response = requests.post(
            f"{client.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            timeout=300  # 5分钟超时
        )
        
        elapsed = time.time() - start_time
        
        print(f"非流式响应: {response.status_code} (耗时: {elapsed:.1f}s)")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("✅ 非流式请求成功!")
            
            # 尝试解析JSON响应
            try:
                result = response.json()
                print("📄 响应内容:")
                
                if isinstance(result, dict):
                    for key, value in result.items():
                        if key == 'audio' and isinstance(value, str):
                            print(f"   {key}: [音频数据 {len(value)} 字符]")
                        elif key == 'text':
                            print(f"   {key}: {value}")
                        else:
                            print(f"   {key}: {str(value)[:100]}...")
                else:
                    print(f"   原始响应: {str(result)[:500]}...")
                    
            except Exception as json_error:
                print(f"📄 非JSON响应内容:")
                print(response.text[:1000] + "..." if len(response.text) > 1000 else response.text)
                
        else:
            print(f"❌ 非流式请求失败: {response.text}")
    
    except Exception as e:
        print(f"❌ 非流式请求异常: {e}")


def test_simple_completions():
    """测试简单的completions请求"""
    print("\n🔬 对比测试：简单completions请求")
    
    try:
        base_url = "http://localhost:32550"
        headers = {"uid": "test_client"}
        
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "请回答：1+1等于多少？"},
            timeout=30
        )
        
        print(f"   简单请求响应: {response.status_code}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"   响应内容: {result}")
                print("   ✅ 简单completions请求正常")
            except:
                print(f"   响应文本: {response.text[:200]}...")
                print("   ✅ 收到响应，但格式可能不同")
        else:
            print(f"   ❌ 简单请求失败: {response.text}")
        
    except Exception as e:
        print(f"   ❌ 简单请求测试失败: {e}")


if __name__ == "__main__":
    # 主要的非流式音频处理测试
    test_non_stream_audio()
    
    # 对比的简单文本处理测试
    test_simple_completions()
    
    print("\n💡 非流式处理的优势:")
    print("   1. 避免了SSE流处理的复杂性")
    print("   2. 更容易调试和错误处理") 
    print("   3. 适合一次性音频处理场景")
    print("\n📝 如果非流式成功而流式失败，说明问题在SSE流处理部分") 