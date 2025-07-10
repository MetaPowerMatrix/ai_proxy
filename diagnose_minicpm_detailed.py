#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCPM 详细诊断工具
分析服务端处理问题
"""

import requests
import json
import time
import base64
import os
from minicpm_client import MiniCPMClient


def test_simple_requests():
    """测试简单的API请求"""
    print("🔍 测试基础API请求...")
    
    base_url = "http://localhost:32550"
    uid = "diagnostic_client"
    
    # 1. 健康检查
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        print(f"✅ 健康检查: {response.status_code}")
        if response.text:
            print(f"   响应: {response.text[:200]}")
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False
    
    # 2. 测试简单completions请求（无音频）
    print("\n📝 测试简单completions请求...")
    try:
        headers = {"uid": uid}
        simple_data = {"prompt": "Hello, how are you?"}
        
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json=simple_data,
            timeout=30
        )
        
        print(f"   状态码: {response.status_code}")
        print(f"   响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            print(f"   响应内容: {response.text[:300]}...")
        else:
            print(f"   错误响应: {response.text}")
            
    except Exception as e:
        print(f"❌ 简单completions请求失败: {e}")
    
    # 3. 测试流式completions请求（无音频）
    print("\n🌊 测试流式completions请求...")
    try:
        headers = {
            "uid": uid,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "Say hello"},
            stream=True,
            timeout=30
        )
        
        print(f"   状态码: {response.status_code}")
        print(f"   内容类型: {response.headers.get('content-type', 'unknown')}")
        
        if response.status_code == 200:
            # 尝试读取一些流数据
            print("   开始读取流数据...")
            chunk_count = 0
            start_time = time.time()
            
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
                    chunk_count += 1
                    print(f"   收到数据块 {chunk_count}: {len(chunk)} 字符")
                    print(f"   内容预览: {chunk[:100]}...")
                    
                    if chunk_count >= 3:  # 只读取前几个chunk
                        print("   已收到足够的测试数据")
                        break
                
                # 防止无限等待
                if time.time() - start_time > 15:
                    print("   ⚠️ 15秒超时，停止读取")
                    break
            
            if chunk_count == 0:
                print("   ⚠️ 没有收到任何数据块")
        
    except Exception as e:
        print(f"❌ 流式completions请求失败: {e}")
    
    return True


def test_audio_upload():
    """测试音频上传功能"""
    print("\n🎵 测试音频上传...")
    
    # 检查测试音频文件
    if not os.path.exists("test_audio.wav"):
        print("❌ 测试音频文件不存在")
        return False
    
    client = MiniCPMClient()
    
    # 1. 测试音频加载
    try:
        audio_base64 = client.load_audio_file("test_audio.wav")
        print(f"✅ 音频文件加载成功: {len(audio_base64)} 字符的base64数据")
    except Exception as e:
        print(f"❌ 音频文件加载失败: {e}")
        return False
    
    # 2. 测试stream接口
    print("\n📤 测试stream接口...")
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
            timeout=60
        )
        
        print(f"   Stream响应: {response.status_code}")
        if response.status_code != 200:
            print(f"   错误: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Stream接口测试失败: {e}")
        return False
    
    # 3. 测试带超长超时的completions请求
    print("\n⏱️ 测试长超时completions请求...")
    try:
        headers = {
            "uid": client.uid,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        response = requests.post(
            f"{client.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            stream=True,
            timeout=180  # 3分钟超时
        )
        
        print(f"   状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("   开始读取音频处理结果...")
            start_time = time.time()
            chunk_count = 0
            data_received = False
            
            try:
                for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                    current_time = time.time()
                    elapsed = current_time - start_time
                    
                    if chunk:
                        chunk_count += 1
                        data_received = True
                        print(f"   📦 收到数据块 {chunk_count} (耗时: {elapsed:.1f}s)")
                        print(f"      内容: {chunk[:200]}...")
                        
                        # 检查是否包含音频或结束标记
                        if '"audio"' in chunk or '"text"' in chunk or '[DONE]' in chunk:
                            print("   🎉 收到有效的音频/文本数据！")
                            break
                    
                    # 超时检查
                    if elapsed > 180:
                        print(f"   ⚠️ 3分钟超时")
                        break
                        
                    # 进度显示
                    if int(elapsed) % 30 == 0 and elapsed > 0:
                        print(f"   ⏳ 已等待 {elapsed:.0f}s...")
                
                if not data_received:
                    print("   ❌ 没有收到任何响应数据")
                    return False
                else:
                    print("   ✅ 成功收到服务端响应！")
                    return True
                    
            except Exception as read_error:
                print(f"   ❌ 读取响应时出错: {read_error}")
                return False
        
    except Exception as e:
        print(f"❌ 长超时completions请求失败: {e}")
        return False
    
    return True


def check_server_logs():
    """提示检查服务端日志"""
    print("\n📋 服务端诊断建议:")
    print("   如果上述测试都失败，请检查MiniCPM服务端日志：")
    print("   1. 查看服务启动日志是否有错误")
    print("   2. 检查模型是否正确加载")
    print("   3. 查看处理音频时是否有异常")
    print("   4. 确认服务端配置是否正确")
    print("\n   常见服务端问题：")
    print("   - 模型文件损坏或未找到")
    print("   - GPU内存不足")
    print("   - 音频处理组件异常")
    print("   - 依赖库版本不兼容")


def main():
    print("=" * 60)
    print("MiniCPM 详细诊断工具")
    print("=" * 60)
    
    # 1. 基础API测试
    print("\n🔧 第1步：基础API功能测试")
    if not test_simple_requests():
        print("❌ 基础API测试失败，请检查服务是否正常启动")
        check_server_logs()
        return
    
    print("✅ 基础API测试通过")
    
    # 2. 音频上传测试
    print("\n🎵 第2步：音频处理功能测试")
    if not test_audio_upload():
        print("❌ 音频处理测试失败")
        check_server_logs()
        return
    
    print("✅ 所有测试通过！MiniCPM服务运行正常")


if __name__ == "__main__":
    main() 