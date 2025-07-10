#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCPM 非流式音频处理测试 - 修复版
解决uid冲突问题
"""

import os
import time
import requests
import uuid
from minicpm_client import MiniCPMClient


def test_non_stream_audio_fixed():
    """测试非流式的音频处理 - 修复uid冲突"""
    
    print("=" * 60)
    print("MiniCPM 非流式音频处理测试 - 修复版")
    print("=" * 60)
    
    # 检查音频文件
    if not os.path.exists("test_audio.wav"):
        print("❌ 测试音频文件不存在")
        return
    
    # 生成唯一的UID避免冲突
    unique_uid = f"test_client_{int(time.time() * 1000)}"
    print(f"🆔 使用唯一UID: {unique_uid}")
    
    # 基础配置
    base_url = "http://localhost:32550"
    
    # 1. 健康检查
    print("1️⃣ 检查服务状态...")
    try:
        health_response = requests.get(f"{base_url}/health", timeout=10)
        if health_response.status_code != 200:
            print("❌ MiniCPM服务不可用")
            return
        print("✅ MiniCPM服务正常")
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return
    
    # 2. 加载音频
    print("2️⃣ 加载音频文件...")
    try:
        with open("test_audio.wav", "rb") as f:
            import base64
            audio_base64 = base64.b64encode(f.read()).decode('utf-8')
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
        
        headers = {
            "uid": unique_uid, 
            "Content-Type": "application/json"
        }
        print(f"📤 Stream请求使用UID: {unique_uid}")
        
        response = requests.post(
            f"{base_url}/api/v1/stream",
            headers=headers,
            json=stream_data,
            timeout=120  # 2分钟
        )
        
        print(f"Stream响应: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Stream请求失败: {response.text}")
            
            # 分析具体错误
            if "uid changed" in response.text:
                print("🔍 这是UID冲突错误，可能有其他客户端在使用")
                # 生成新的UID再试一次
                unique_uid = f"test_client_{int(time.time() * 1000) + 1}"
                print(f"🔄 重试使用新UID: {unique_uid}")
                
                headers["uid"] = unique_uid
                response = requests.post(
                    f"{base_url}/api/v1/stream",
                    headers=headers,
                    json=stream_data,
                    timeout=120
                )
                print(f"重试Stream响应: {response.status_code}")
                if response.status_code != 200:
                    print(f"❌ 重试Stream请求仍然失败: {response.text}")
                    return
                else:
                    print("✅ 重试Stream请求成功")
            else:
                return
        else:
            print("✅ Stream请求成功")
            
    except Exception as e:
        print(f"❌ Stream请求异常: {e}")
        return
    
    # 4. 等待一下，确保服务端处理完stream请求
    print("⏳ 等待2秒，确保stream请求处理完成...")
    time.sleep(2)
    
    # 5. 发送非流式completions请求
    print("4️⃣ 发送非流式completions请求...")
    try:
        headers = {
            "uid": unique_uid,  # 使用相同的UID
            "Content-Type": "application/json"
        }
        print(f"📤 Completions请求使用UID: {unique_uid}")
        
        start_time = time.time()
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            timeout=300  # 5分钟超时
        )
        
        elapsed = time.time() - start_time
        
        print(f"非流式响应: {response.status_code} (耗时: {elapsed:.1f}s)")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("✅ 非流式请求成功!")
            
            # 尝试解析响应
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
                content = response.text
                print(content[:1000] + "..." if len(content) > 1000 else content)
                
        else:
            print(f"❌ 非流式请求失败: {response.text}")
            
            # 分析错误原因
            if "uid changed" in response.text:
                print("🔍 仍然是UID冲突错误")
                print("💡 建议：检查是否有其他客户端正在连接服务")
            elif "timeout" in response.text.lower():
                print("🔍 这是超时错误，模型可能在处理但耗时很长")
            else:
                print("🔍 未知错误，请检查服务端日志")
    
    except Exception as e:
        print(f"❌ 非流式请求异常: {e}")


def test_simple_text_only():
    """测试纯文本请求，不涉及音频"""
    print("\n🔬 对比测试：纯文本请求")
    
    try:
        base_url = "http://localhost:32550"
        unique_uid = f"text_test_{int(time.time() * 1000)}"
        
        headers = {
            "uid": unique_uid,
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "请简单回答：你好吗？"},
            timeout=30
        )
        
        print(f"   文本请求响应: {response.status_code}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"   响应内容: {result}")
                print("   ✅ 纯文本请求正常")
            except:
                print(f"   响应文本: {response.text[:200]}...")
                print("   ✅ 收到响应，但格式可能不同")
        else:
            print(f"   ❌ 文本请求失败: {response.text}")
        
    except Exception as e:
        print(f"   ❌ 文本请求测试失败: {e}")


def check_active_connections():
    """检查是否有其他活跃的连接"""
    print("\n🔍 诊断信息:")
    print("   如果持续出现'uid changed'错误，可能原因：")
    print("   1. 有其他客户端正在连接MiniCPM服务")
    print("   2. 之前的连接没有正确关闭")
    print("   3. 服务端的session管理有问题")
    print("\n   建议解决方案：")
    print("   1. 重启MiniCPM服务清除所有连接")
    print("   2. 检查是否有其他程序在使用该服务")
    print("   3. 使用更唯一的UID（包含随机数）")


if __name__ == "__main__":
    # 主要的音频处理测试
    test_non_stream_audio_fixed()
    
    # 对比的文本处理测试
    test_simple_text_only()
    
    # 诊断信息
    check_active_connections()
    
    print("\n💡 总结:")
    print("   1. 如果非流式音频请求成功，说明音频处理功能正常")
    print("   2. 如果仍然失败，问题可能在服务端配置或资源限制")
    print("   3. uid冲突通常是因为有多个客户端同时连接") 