#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCPM 扩展流式测试
增加超长超时和详细监控
"""

import os
import time
import requests
from minicpm_client import MiniCPMClient


def test_extended_audio_processing():
    """测试扩展的音频处理，包含详细监控"""
    
    print("=" * 60)
    print("MiniCPM 扩展音频处理测试")
    print("=" * 60)
    
    # 检查音频文件
    if not os.path.exists("test_audio.wav"):
        print("❌ 测试音频文件不存在")
        return
    
    # 初始化客户端
    client = MiniCPMClient()
    
    # 1. 健康检查
    print("1️⃣ 检查服务状态...")
    if not client.check_service_status():
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
            timeout=120  # 2分钟
        )
        
        print(f"Stream响应: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Stream请求失败: {response.text}")
            return
            
    except Exception as e:
        print(f"❌ Stream请求异常: {e}")
        return
    
    # 4. 发送completions请求，使用超长超时
    print("4️⃣ 开始超长超时的completions请求...")
    try:
        headers = {
            "uid": client.uid,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        # 使用10分钟超时
        response = requests.post(
            f"{client.base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": ""},
            stream=True,
            timeout=600  # 10分钟超时
        )
        
        print(f"Completions响应: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Completions请求失败: {response.text}")
            return
        
        # 5. 处理SSE流，包含详细监控
        print("5️⃣ 开始处理SSE流（最长等待10分钟）...")
        print("📊 进度监控:")
        
        start_time = time.time()
        chunk_count = 0
        total_data = ""
        last_progress_time = start_time
        
        try:
            # 设置socket超时为120秒
            if hasattr(response.raw, '_connection') and hasattr(response.raw._connection, 'sock'):
                response.raw._connection.sock.settimeout(120)
                print("🔧 已设置socket超时: 120秒")
            
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                current_time = time.time()
                elapsed = current_time - start_time
                
                if chunk:
                    chunk_count += 1
                    total_data += chunk
                    
                    print(f"   📦 数据块 {chunk_count} (耗时: {elapsed:.1f}s, 大小: {len(chunk)})")
                    
                    # 显示数据内容（前100字符）
                    preview = chunk.replace('\n', '\\n').replace('\r', '\\r')
                    print(f"      内容: {preview[:100]}...")
                    
                    # 检查是否收到有效数据
                    if any(keyword in chunk for keyword in ['"audio"', '"text"', '"response"', '[DONE]']):
                        print("   🎉 收到有效的音频/文本响应数据!")
                        
                        if '[DONE]' in chunk:
                            print("   ✅ 流处理完成!")
                            break
                    
                    last_progress_time = current_time
                
                # 超时检查
                if elapsed > 600:  # 10分钟
                    print(f"   ⚠️ 已达到10分钟超时限制")
                    break
                
                # 进度显示（每60秒）
                if current_time - last_progress_time >= 60:
                    print(f"   ⏳ 已等待 {elapsed:.0f}s，收到 {chunk_count} 个数据块...")
                    last_progress_time = current_time
                
                # 检查是否长时间无数据
                if chunk_count > 0 and elapsed > 300 and chunk_count < 5:  # 5分钟后仍然很少数据
                    print("   ⚠️ 长时间收到很少数据，可能处理异常")
        
        except Exception as stream_error:
            elapsed = time.time() - start_time
            print(f"   ❌ 流处理异常 (耗时: {elapsed:.1f}s): {stream_error}")
            
            # 分析异常类型
            if "Read timed out" in str(stream_error):
                print("   🔍 这是socket读取超时，说明服务端在处理但响应很慢")
            elif "Connection" in str(stream_error):
                print("   🔍 这是连接问题，可能服务端处理时崩溃了")
            else:
                print(f"   🔍 未知异常类型: {type(stream_error)}")
        
        # 6. 结果统计
        final_time = time.time() - start_time
        print(f"\n📊 处理统计:")
        print(f"   总耗时: {final_time:.1f}s")
        print(f"   数据块数: {chunk_count}")
        print(f"   总数据量: {len(total_data)} 字符")
        
        if chunk_count == 0:
            print("❌ 没有收到任何数据 - 可能的原因:")
            print("   1. 模型加载失败或卡住")
            print("   2. 音频处理组件异常") 
            print("   3. GPU内存不足")
            print("   4. 服务端配置问题")
        elif chunk_count < 5:
            print("⚠️ 收到很少数据 - 可能处理异常")
        else:
            print("✅ 收到了一些数据，但可能处理未完成")
        
        # 显示部分数据用于调试
        if total_data:
            print(f"\n📄 收到的数据预览:")
            print(total_data[:500] + "..." if len(total_data) > 500 else total_data)
            
    except Exception as e:
        print(f"❌ Completions请求异常: {e}")


def test_simple_text_request():
    """测试简单的文本请求作为对比"""
    print("\n🔬 对比测试：简单文本请求")
    
    try:
        base_url = "http://localhost:32550"
        headers = {
            "uid": "test_client",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "Hello, please say hi back to me."},
            stream=True,
            timeout=60
        )
        
        print(f"   文本请求响应: {response.status_code}")
        
        if response.status_code == 200:
            print("   开始读取文本响应...")
            start_time = time.time()
            chunk_count = 0
            
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
                    chunk_count += 1
                    elapsed = time.time() - start_time
                    print(f"   📦 文本数据块 {chunk_count} (耗时: {elapsed:.1f}s)")
                    print(f"      内容: {chunk[:100]}...")
                    
                    if chunk_count >= 3 or '[DONE]' in chunk:
                        print("   ✅ 文本请求响应正常")
                        break
                
                if time.time() - start_time > 30:
                    break
            
            if chunk_count == 0:
                print("   ❌ 文本请求也没有响应 - 服务端可能有严重问题")
            else:
                print("   ✅ 文本请求正常，问题可能在音频处理部分")
        
    except Exception as e:
        print(f"   ❌ 文本请求测试失败: {e}")


if __name__ == "__main__":
    # 主要的音频处理测试
    test_extended_audio_processing()
    
    # 对比的文本处理测试
    test_simple_text_request()
    
    print("\n💡 如果问题持续存在，建议:")
    print("   1. 检查服务端日志，查看具体错误信息")
    print("   2. 确认模型文件是否正确加载")
    print("   3. 监控服务端CPU/GPU/内存使用情况")
    print("   4. 尝试重启MiniCPM服务") 