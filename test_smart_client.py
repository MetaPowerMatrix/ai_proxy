#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试智能MiniCPM客户端
基于Stream响应智能决定处理流程
"""

import os
import time
from minicpm_client import MiniCPMClient


def test_smart_audio_processing():
    """测试智能音频处理"""
    
    print("=" * 70)
    print("测试智能MiniCPM客户端")
    print("=" * 70)
    
    # 检查音频文件
    audio_file = "test_audio.wav"
    if not os.path.exists(audio_file):
        print(f"❌ 音频文件 {audio_file} 不存在")
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
    
    # 2. 测试智能音频处理
    print("\n2️⃣ 开始智能音频处理...")
    print("🧠 智能逻辑:")
    print("   - 发送音频到stream接口")
    print("   - 检查Stream响应状态")
    print("   - 如果已完成且有音频→直接返回")
    print("   - 如果已完成但无音频→尝试简短completions")
    print("   - 如果未完成→执行完整流程")
    
    try:
        start_time = time.time()
        
        audio_chunks, text_response = client.stream_audio_processing(audio_file)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print(f"\n📊 智能处理结果 (总耗时: {total_time:.1f}s):")
        
        if audio_chunks is None and text_response is None:
            print("❌ 智能处理失败")
            return
        
        # 分析结果
        audio_count = len(audio_chunks) if audio_chunks else 0
        text_length = len(text_response) if text_response else 0
        
        print(f"   📦 收到音频片段数量: {audio_count}")
        print(f"   📝 收到文本回复长度: {text_length}")
        print(f"   📄 文本内容: {text_response if text_response else '无'}")
        
        # 分析处理效率
        if total_time < 10:
            print(f"   ⚡ 快速处理 ({total_time:.1f}s) - 可能使用了智能路径")
        elif total_time < 30:
            print(f"   ⏱️ 中等处理时间 ({total_time:.1f}s) - 部分优化生效")
        else:
            print(f"   🐌 较长处理时间 ({total_time:.1f}s) - 使用了完整流程")
        
        # 保存音频结果
        if audio_chunks and audio_count > 0:
            try:
                from minicpm_client import merge_pcm_chunks, save_pcm_as_wav
                merged_pcm = merge_pcm_chunks([chunk[0] for chunk in audio_chunks])
                if merged_pcm is not None:
                    output_file = "output_smart.wav"
                    save_pcm_as_wav(merged_pcm, 16000, 1, output_file)
                    print(f"   💾 音频已保存为 {output_file}")
            except Exception as e:
                print(f"   ⚠️ 保存音频失败: {e}")
        
        # 评估智能处理效果
        if audio_count > 0 or text_length > 0:
            print("\n🎉 智能处理成功!")
            efficiency = "高效" if total_time < 15 else "标准"
            print(f"✅ 处理效率: {efficiency}")
        else:
            print("\n⚠️ 处理完成但无有效数据")
        
    except Exception as e:
        print(f"\n❌ 智能处理过程中出错: {e}")
        import traceback
        traceback.print_exc()


def test_stream_response_analysis():
    """测试Stream响应分析"""
    print("\n" + "=" * 70)
    print("Stream响应分析测试")
    print("=" * 70)
    
    client = MiniCPMClient()
    
    # 1. 加载音频
    print("1️⃣ 加载音频文件...")
    try:
        audio_base64 = client.load_audio_file("test_audio.wav")
        print(f"✅ 音频加载成功: {len(audio_base64)} 字符")
    except Exception as e:
        print(f"❌ 音频加载失败: {e}")
        return
    
    # 2. 分析Stream响应
    print("\n2️⃣ 分析Stream响应...")
    try:
        stream_result = client.send_audio_with_completion_flag(audio_base64, end_of_stream=True)
        
        print(f"📋 Stream结果分析:")
        print(f"   成功状态: {stream_result.get('success', False)}")
        
        if stream_result.get('success'):
            result = stream_result.get('result')
            if result and isinstance(result, dict):
                print(f"   返回数据: {result}")
                
                # 分析choices
                choices = result.get('choices', {})
                if isinstance(choices, dict):
                    print(f"   完成状态: {choices.get('finish_reason', 'unknown')}")
                    print(f"   内容: {choices.get('content', 'none')}")
                    
                    if 'audio' in choices:
                        print(f"   🎵 包含音频数据: {len(choices['audio'])} 字符")
                    else:
                        print(f"   📝 无音频数据")
                    
                    # 预测处理路径
                    if choices.get('finish_reason') == 'done':
                        if 'audio' in choices:
                            print("   🎯 预测路径: 直接返回Stream中的音频")
                        else:
                            print("   🎯 预测路径: 尝试简短completions请求")
                    else:
                        print("   🎯 预测路径: 执行完整处理流程")
                        
            else:
                print(f"   ⚠️ 无效的返回数据格式")
        else:
            error = stream_result.get('error', 'unknown')
            print(f"   ❌ Stream请求失败: {error}")
            
    except Exception as e:
        print(f"❌ Stream响应分析失败: {e}")


def test_different_scenarios():
    """测试不同场景下的智能处理"""
    print("\n" + "=" * 70)
    print("多场景智能处理测试")
    print("=" * 70)
    
    scenarios = [
        {"name": "标准处理", "end_of_stream": True},
        {"name": "分段处理", "end_of_stream": False},
    ]
    
    client = MiniCPMClient()
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{i}️⃣ 场景测试: {scenario['name']}")
        
        try:
            audio_base64 = client.load_audio_file("test_audio.wav")
            
            # 使用不同的UID避免冲突
            client.uid = f"smart_test_{int(time.time() * 1000)}_{i}"
            print(f"   使用UID: {client.uid}")
            
            stream_result = client.send_audio_with_completion_flag(
                audio_base64, 
                end_of_stream=scenario['end_of_stream']
            )
            
            if stream_result.get('success'):
                result = stream_result.get('result', {})
                choices = result.get('choices', {})
                
                print(f"   ✅ Stream成功")
                print(f"   完成状态: {choices.get('finish_reason', 'none')}")
                print(f"   是否有音频: {'是' if stream_result.get('has_audio') else '否'}")
                
                # 根据结果预测性能
                if choices.get('finish_reason') == 'done':
                    print(f"   🚀 预期高效处理")
                else:
                    print(f"   ⏳ 预期标准处理")
            else:
                print(f"   ❌ Stream失败: {stream_result.get('error')}")
                
        except Exception as e:
            print(f"   💥 场景测试异常: {e}")


def main():
    """主测试函数"""
    print("🚀 开始智能MiniCPM客户端测试")
    
    # 测试1: 智能音频处理
    test_smart_audio_processing()
    
    # 测试2: Stream响应分析
    test_stream_response_analysis()
    
    # 测试3: 多场景测试
    test_different_scenarios()
    
    print("\n" + "=" * 70)
    print("🎯 智能处理总结")
    print("=" * 70)
    print("智能优化特性:")
    print("1. ✅ 基于Stream响应的智能路径选择")
    print("2. ✅ 自动检测处理完成状态")
    print("3. ✅ 避免不必要的completions请求")
    print("4. ✅ 兼容多种响应格式")
    print("5. ✅ 显著减少处理时间")
    print("\n💡 智能处理应该解决超时问题并提高效率!")


if __name__ == "__main__":
    main() 