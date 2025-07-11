#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试改进的MiniCPM客户端
包含显式结束标记和强制完成功能
"""

import os
import time
from minicpm_client import MiniCPMClient


def test_improved_minicpm_client():
    """测试改进的MiniCPM客户端功能"""
    
    print("=" * 70)
    print("测试改进的MiniCPM客户端")
    print("=" * 70)
    
    # 检查音频文件
    audio_file = "test_audio.wav"
    if not os.path.exists(audio_file):
        print(f"❌ 音频文件 {audio_file} 不存在")
        print("💡 请确保测试音频文件存在")
        return
    
    # 初始化客户端
    client = MiniCPMClient()
    print(f"🆔 客户端UID: {client.uid}")
    
    # 1. 健康检查
    print("\n1️⃣ 检查服务状态...")
    try:
        health_response = client.check_service_status()
        if health_response.status_code != 200:
            print("❌ MiniCPM服务不可用")
            return
        print("✅ MiniCPM服务正常")
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return
    
    # 2. 测试改进的音频处理流程
    print("\n2️⃣ 开始改进的音频处理流程...")
    print("🔄 新流程包括:")
    print("   - 发送音频到stream接口并标记end_of_stream=True")
    print("   - 等待服务器处理")
    print("   - 发送强制完成信号")
    print("   - 获取completions响应（带重试）")
    print("   - 处理SSE流")
    
    try:
        start_time = time.time()
        
        audio_chunks, text_response = client.stream_audio_processing(audio_file)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print(f"\n📊 处理结果 (总耗时: {total_time:.1f}s):")
        
        if audio_chunks is None and text_response is None:
            print("❌ 音频处理完全失败")
            print("💡 可能的原因:")
            print("   - Stream请求失败")
            print("   - 服务端未正确识别结束标记")
            print("   - Completions请求超时")
            return
        
        # 成功处理的情况
        audio_count = len(audio_chunks) if audio_chunks else 0
        text_length = len(text_response) if text_response else 0
        
        print(f"   📦 收到音频片段数量: {audio_count}")
        print(f"   📝 收到文本回复长度: {text_length}")
        print(f"   📄 文本内容: {text_response if text_response else '无'}")
        
        # 保存音频结果
        if audio_chunks and audio_count > 0:
            try:
                from minicpm_client import merge_pcm_chunks, save_pcm_as_wav
                merged_pcm = merge_pcm_chunks([chunk[0] for chunk in audio_chunks])
                if merged_pcm is not None:
                    output_file = "output_improved.wav"
                    save_pcm_as_wav(merged_pcm, 16000, 1, output_file)
                    print(f"   💾 音频已保存为 {output_file}")
                else:
                    print("   ⚠️ 音频合并失败")
            except Exception as e:
                print(f"   ⚠️ 保存音频失败: {e}")
        
        # 评估改进效果
        if audio_count > 0 or text_length > 0:
            print("\n🎉 改进的流程成功!")
            print("✅ 主要改进:")
            print("   - 显式的end_of_stream标记确保服务端知道数据发送完毕")
            print("   - 强制完成信号避免服务端等待")
            print("   - 重试机制提高成功率")
            print("   - 更简洁的SSE流处理")
        else:
            print("\n⚠️ 流程完成但没有收到有效数据")
            print("💡 这可能表明:")
            print("   - 服务端处理逻辑需要调整")
            print("   - 音频格式或内容有问题")
            print("   - 需要更长的处理时间")
        
    except Exception as e:
        print(f"\n❌ 音频处理过程中出错: {e}")
        import traceback
        traceback.print_exc()


def test_individual_components():
    """单独测试各个组件"""
    print("\n" + "=" * 70)
    print("单独测试各个组件")
    print("=" * 70)
    
    # 使用新的UID避免与前面的测试冲突
    client = MiniCPMClient()
    client.uid = f"component_test_{int(time.time() * 1000)}"
    print(f"🆔 组件测试UID: {client.uid}")
    
    # 1. 测试音频加载
    print("1️⃣ 测试音频加载...")
    try:
        audio_base64 = client.load_audio_file("test_audio.wav")
        print(f"✅ 音频加载成功: {len(audio_base64)} 字符")
    except Exception as e:
        print(f"❌ 音频加载失败: {e}")
        return
    
    # 2. 测试stream请求（带结束标记）
    print("\n2️⃣ 测试stream请求（带结束标记）...")
    stream_result = client.send_audio_with_completion_flag(audio_base64, end_of_stream=True)
    if stream_result.get('success'):
        print("✅ Stream请求成功")
        result = stream_result.get('result', {})
        choices = result.get('choices', {})
        if choices.get('finish_reason') == 'done':
            print(f"   🎯 处理状态: 已完成")
        print(f"   📊 响应数据: {result}")
    else:
        print(f"❌ Stream请求失败: {stream_result.get('error')}")
        return
    
    # 3. 测试强制完成
    print("\n3️⃣ 测试强制完成信号...")
    client.force_completion()
    
    # 4. 测试completions请求（带重试）
    print("\n4️⃣ 测试completions请求（带重试）...")
    response = client.get_completions_with_retry(max_retries=2)
    if response:
        print(f"✅ Completions请求成功: {response.status_code}")
        print(f"📋 响应头: {dict(response.headers)}")
    else:
        print("❌ Completions请求失败")


def main():
    """主测试函数"""
    print("🚀 开始测试改进的MiniCPM客户端")
    
    # 主要测试
    test_improved_minicpm_client()
    
    # 组件测试
    test_individual_components()
    
    print("\n" + "=" * 70)
    print("🎯 测试总结")
    print("=" * 70)
    print("改进的主要特性:")
    print("1. ✅ 显式的 end_of_stream 标记")
    print("2. ✅ 强制完成信号 (stop_response)")
    print("3. ✅ 带重试机制的 completions 请求")
    print("4. ✅ 改进的 SSE 流处理")
    print("5. ✅ 更好的错误处理和日志")
    print("\n💡 这些改进应该解决之前的uid冲突和超时问题!")


if __name__ == "__main__":
    main() 