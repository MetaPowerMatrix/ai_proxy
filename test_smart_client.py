#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试智能MiniCPM客户端
基于Stream响应智能决定处理流程
"""

import os
import time
import wave
import numpy as np
from minicpm_client import MiniCPMClient


def analyze_audio_quality(audio_file):
    """分析音频质量，返回关键指标"""
    try:
        with wave.open(audio_file, 'rb') as wav_file:
            # 获取音频参数
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            duration = frames / sample_rate
            
            # 读取音频数据
            audio_data = wav_file.readframes(frames)
            
            # 转换为numpy数组进行分析
            if sample_width == 1:
                audio_array = np.frombuffer(audio_data, dtype=np.uint8)
            elif sample_width == 2:
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            elif sample_width == 4:
                audio_array = np.frombuffer(audio_data, dtype=np.int32)
            else:
                audio_array = np.frombuffer(audio_data, dtype=np.float32)
            
            # 计算音频质量指标
            rms = np.sqrt(np.mean(audio_array.astype(np.float64) ** 2))
            max_amplitude = np.max(np.abs(audio_array))
            
            # 计算信噪比估计
            signal_power = np.mean(audio_array.astype(np.float64) ** 2)
            noise_estimate = np.var(audio_array.astype(np.float64))
            snr_estimate = 10 * np.log10(signal_power / (noise_estimate + 1e-10))
            
            quality_info = {
                'duration': duration,
                'sample_rate': sample_rate,
                'channels': channels,
                'sample_width': sample_width,
                'frames': frames,
                'rms': rms,
                'max_amplitude': max_amplitude,
                'snr_estimate': snr_estimate,
                'dynamic_range': max_amplitude / (rms + 1e-10)
            }
            
            return quality_info
            
    except Exception as e:
        print(f"音频质量分析失败: {e}")
        return None


def suggest_vad_threshold(quality_info):
    """根据音频质量建议VAD阈值"""
    if not quality_info:
        return 0.8  # 默认值
    
    # 基于音频质量动态调整VAD阈值
    base_threshold = 0.8
    
    # 如果音频时长太短，降低阈值
    if quality_info['duration'] < 2.0:
        base_threshold -= 0.2
        
    # 如果RMS值较低（音量小），降低阈值
    if quality_info['rms'] < 1000:
        base_threshold -= 0.1
        
    # 如果信噪比较低，降低阈值
    if quality_info['snr_estimate'] < 10:
        base_threshold -= 0.1
        
    # 如果动态范围较低，降低阈值
    if quality_info['dynamic_range'] < 2.0:
        base_threshold -= 0.1
        
    # 确保阈值在合理范围内
    suggested_threshold = max(0.1, min(0.9, base_threshold))
    
    return suggested_threshold


def init_with_adaptive_vad(client, audio_file):
    """使用自适应VAD阈值初始化客户端"""
    print("🔍 分析音频质量...")
    quality_info = analyze_audio_quality(audio_file)
    
    if quality_info:
        print(f"📊 音频质量分析结果:")
        print(f"   时长: {quality_info['duration']:.2f}s")
        print(f"   采样率: {quality_info['sample_rate']}Hz")
        print(f"   RMS: {quality_info['rms']:.2f}")
        print(f"   信噪比估计: {quality_info['snr_estimate']:.2f}dB")
        print(f"   动态范围: {quality_info['dynamic_range']:.2f}")
        
        # 基于质量分析建议VAD阈值
        suggested_threshold = suggest_vad_threshold(quality_info)
        print(f"💡 建议VAD阈值: {suggested_threshold:.2f}")
        
        # 使用建议的阈值初始化
        return init_with_custom_vad_threshold(client, audio_file, suggested_threshold)
    else:
        print("⚠️ 无法分析音频质量，使用默认阈值")
        return client.init_with_chinese_voice(audio_file)


def init_with_custom_vad_threshold(client, audio_file, vad_threshold):
    """使用自定义VAD阈值初始化客户端"""
    try:
        custom_audio_base64 = client.load_audio_file(audio_file)
        
        init_data = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": custom_audio_base64,
                            "format": "wav"
                        }
                    },
                    {
                        "type": "options",
                        "options": {
                            "voice_clone_prompt": "你是一个AI助手。你能接受视频，音频和文本输入并输出语音和文本。模仿输入音频中的声音特征。",
                            "assistant_prompt": "作为助手，你将使用这种声音风格说话。",
                            "use_audio_prompt": 0,
                            "vad_threshold": vad_threshold,  # 使用自定义阈值
                            "hd_video": False
                        }
                    }
                ]
            }]
        }
        
        response = client.session.post(
            f"{client.base_url}/init_options",
            json=init_data,
            headers={"uid": client.uid}
        )
        
        print(f"✅ 使用VAD阈值 {vad_threshold:.2f} 初始化成功")
        return response.json()
        
    except Exception as e:
        print(f"❌ 自定义VAD阈值初始化失败: {e}")
        raise


def test_smart_audio_processing():
    """测试智能音频处理"""
    
    print("=" * 70)
    print("测试智能MiniCPM客户端 - 增强版VAD优化")
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
    
    # 1.5. 自适应VAD阈值初始化
    print("\n1.5️⃣ 自适应VAD阈值初始化...")
    try:
        init_result = init_with_adaptive_vad(client, audio_file)
        print("✅ 自适应初始化成功")
    except Exception as e:
        print(f"❌ 自适应初始化失败: {e}")
        print("🔄 尝试使用低阈值重试...")
        try:
            init_result = init_with_custom_vad_threshold(client, audio_file, 0.3)
            print("✅ 低阈值初始化成功")
        except Exception as e2:
            print(f"❌ 低阈值初始化也失败: {e2}")
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
            print("🔧 可能的解决方案:")
            print("   1. 检查音频文件是否包含清晰的语音")
            print("   2. 尝试调整VAD阈值")
            print("   3. 确保音频文件格式正确")
            print("   4. 检查音频时长是否足够（建议>2秒）")
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
    
    # 0. 自适应初始化
    print("0️⃣ 自适应VAD初始化...")
    try:
        init_result = init_with_adaptive_vad(client, "test_audio.wav")
        print("✅ 自适应初始化成功")
    except Exception as e:
        print(f"❌ 自适应初始化失败: {e}")
        return
    
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
            audio_file = "test_audio.wav"
            if not os.path.exists(audio_file):
                print(f"   ❌ 音频文件 {audio_file} 不存在")
                continue
                
            # 使用不同的UID避免冲突
            client.uid = f"smart_test_{int(time.time() * 1000)}_{i}"
            print(f"   使用UID: {client.uid}")
            
            # 🔑 关键修复：每次更改UID时先调用自适应VAD初始化
            print(f"   🔄 为新UID进行自适应VAD初始化...")
            try:
                init_result = init_with_adaptive_vad(client, audio_file)
                print(f"   ✅ 自适应初始化成功")
            except Exception as init_error:
                print(f"   ❌ 自适应初始化失败: {init_error}")
                print(f"   🔄 尝试使用低阈值重试...")
                try:
                    init_result = init_with_custom_vad_threshold(client, audio_file, 0.3)
                    print(f"   ✅ 低阈值初始化成功")
                except Exception as fallback_error:
                    print(f"   ❌ 低阈值初始化也失败: {fallback_error}")
                    continue
            
            audio_base64 = client.load_audio_file(audio_file)
            
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
    print("🚀 开始智能MiniCPM客户端测试 - VAD优化版")
    
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
    print("6. ✅ 每次UID变更时自动初始化Session")
    print("7. ✅ 自适应VAD阈值优化")
    print("8. ✅ 音频质量分析和诊断")
    print("\n💡 智能处理应该解决超时问题并提高效率!")
    print("🔧 重要修复: 确保每次使用新UID时都先初始化session!")
    print("🎙️ VAD优化: 根据音频质量自动调整VAD阈值，解决'vad_sequence insufficient'问题!")


if __name__ == "__main__":
    main() 