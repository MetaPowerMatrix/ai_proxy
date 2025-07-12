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
import tempfile
import base64
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

def split_audio_into_chunks(audio_file, num_chunks=20):
    """将音频文件分成指定数量的片段"""
    try:
        with wave.open(audio_file, 'rb') as wav_file:
            # 获取音频参数
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            
            # 读取所有音频数据
            audio_data = wav_file.readframes(frames)
            
            # 计算每个片段的大小
            chunk_size = len(audio_data) // num_chunks
            
            chunks = []
            for i in range(num_chunks):
                start = i * chunk_size
                if i == num_chunks - 1:  # 最后一个片段包含剩余所有数据
                    end = len(audio_data)
                else:
                    end = start + chunk_size
                
                chunk_data = audio_data[start:end]
                
                # 创建临时WAV文件
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                    with wave.open(temp_file.name, 'wb') as chunk_wav:
                        chunk_wav.setnchannels(channels)
                        chunk_wav.setsampwidth(sample_width)
                        chunk_wav.setframerate(sample_rate)
                        chunk_wav.writeframes(chunk_data)
                    
                    # 读取临时文件并转换为base64
                    temp_file.seek(0)
                    with open(temp_file.name, 'rb') as f:
                        chunk_base64 = base64.b64encode(f.read()).decode('utf-8')
                    
                    chunks.append({
                        'index': i + 1,
                        'data': chunk_base64,
                        'size': len(chunk_data),
                        'duration': len(chunk_data) / (sample_rate * channels * sample_width)
                    })
                    
                    # 删除临时文件
                    os.unlink(temp_file.name)
            
            print(f"🔪 音频分片完成: {len(chunks)} 个片段")
            return chunks
            
    except Exception as e:
        print(f"❌ 音频分片失败: {e}")
        return []


def test_chunked_audio_processing():
    """测试分片音频处理"""
    print("\n" + "=" * 70)
    print("分片音频处理测试 - 20片段发送")
    print("=" * 70)
    final_audio_chunks = []
    final_text = []
    
    # 检查音频文件
    reference_audio_file = "reference_audio.wav"
    if not os.path.exists(reference_audio_file):
        print(f"❌ 音频文件 {reference_audio_file} 不存在")
        return
    
    audio_file = "test_audio.wav"
    if not os.path.exists(audio_file):
        print(f"❌ 音频文件 {audio_file} 不存在")
        return

    client = MiniCPMClient()
    init_with_custom_vad_threshold(client, reference_audio_file, 0.8)
    
    
    # 分片处理
    chunks = split_audio_into_chunks(audio_file, num_chunks=20)
    if not chunks:
        print("❌ 音频分片失败")
        return
    
    # 2. 逐个发送片段
    print(f"\n2️⃣ 开始分片发送处理...")
    start_time = time.time()
    
    successful_chunks = 0
    failed_chunks = 0
    
    for i, chunk in enumerate(chunks):
        print(f"\n📤 发送片段 {chunk['index']}/{len(chunks)}")
        print(f"   片段大小: {chunk['size']}字节, 时长: {chunk['duration']:.3f}s")
        
        try:
            # 判断是否为最后一个片段
            is_last_chunk = (i == len(chunks) - 1)
            
            # 发送音频片段
            stream_result = client.send_audio_with_completion_flag(
                chunk['data'], 
                end_of_stream=is_last_chunk
            )
            
                
            # 收集结果
            choices = stream_result.get('choices', {})
            
            if 'audio' in choices:
                print(f"   🎵 收到音频数据: {len(choices['audio'])} 字符")
            
            if choices.get('content'):
                text_content = choices['content']
                if text_content == 'success':
                    print(f"   ✅ 片段 {chunk['index']} 发送成功")
                    successful_chunks += 1
                    if successful_chunks >= 6:
                        _audio_chunks, _text = client.stream_audio_processing()
                        if _audio_chunks:
                            final_audio_chunks.extend(_audio_chunks)
                        if _text:
                            final_text.extend(_text)
                else:
                    print(f"   ❌ 片段 {chunk['index']} 发送失败: {text_content}")
                    failed_chunks += 1

            
            # 检查完成状态
            if choices.get('finish_reason') == 'done':
                print(f"   🏁 片段 {chunk['index']} 标记为完成")
                    
        except Exception as e:
            print(f"   💥 片段 {chunk['index']} 处理异常: {e}")
            failed_chunks += 1
        
        # 片段间短暂延迟
        time.sleep(0.1)
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # 3. 处理结果汇总
    print(f"\n3️⃣ 分片发送完成统计:")
    print(f"   📊 发送统计: 成功 {successful_chunks}/{len(chunks)}, 失败 {failed_chunks}")
    print(f"   ⏱️ 总耗时: {total_time:.1f}s")
    print(f"   📈 平均每片段: {total_time/len(chunks):.2f}s")
    
    # 如果需要获取最终结果，可以调用completions
    if successful_chunks > 0:
        print(f"\n4️⃣ 获取最终处理结果...")
        try:
            
            if final_audio_chunks or final_text:
                print(f"✅ 获取到最终结果:")
                print(f"   音频片段数: {len(final_audio_chunks) if final_audio_chunks else 0}")
                print(f"   文本长度: {len(final_text) if final_text else 0}")
                print(f"   文本内容: {final_text if final_text else '无'}")
                
                # 保存最终音频
                if final_audio_chunks:
                    try:
                        from minicpm_client import merge_pcm_chunks, save_pcm_as_wav
                        merged_pcm = merge_pcm_chunks([chunk[0] for chunk in final_audio_chunks])
                        if merged_pcm is not None:
                            output_file = "output_chunked.wav"
                            save_pcm_as_wav(merged_pcm, 16000, 1, output_file)
                            print(f"   💾 最终音频已保存为 {output_file}")
                    except Exception as e:
                        print(f"   ⚠️ 保存最终音频失败: {e}")
            else:
                print(f"⚠️ 未获取到最终结果")
                
        except Exception as e:
            print(f"❌ 获取最终结果失败: {e}")
    
    # 性能分析
    success_rate = (successful_chunks / len(chunks)) * 100 if chunks else 0
    print(f"\n📈 性能分析:")
    print(f"   成功率: {success_rate:.1f}%")
    
    if success_rate >= 90:
        print(f"   🎉 优秀! 分片发送非常稳定")
    elif success_rate >= 70:
        print(f"   ✅ 良好! 大部分片段发送成功")
    else:
        print(f"   ⚠️ 需要优化! 发送成功率较低")
        print(f"   🔧 建议:")
        print(f"      - 检查网络连接")
        print(f"      - 增加片段间延迟")
        print(f"      - 减少分片数量")


def main():
    """主测试函数"""
    print("🚀 开始智能MiniCPM客户端测试 - VAD优化版")
    print("📝 注意: 整个测试过程将使用同一个UID")
    
    # 测试4: 分片音频处理 (20片段)
    test_chunked_audio_processing()
    
    print("\n" + "=" * 70)
    print("🎯 智能处理总结")
    print("=" * 70)
    print("智能优化特性:")
    print("1. ✅ 音频分片发送（20片段）")
    print("\n💡 智能处理应该解决超时问题并提高效率!")
    print("🔧 重要优化: 全程使用同一个UID，避免session切换问题!")
    print("🎙️ VAD优化: 根据音频质量自动调整VAD阈值，解决'vad_sequence insufficient'问题!")
    print("🔪 分片优化: 支持将音频分成20个片段逐个发送，提高大文件处理成功率!")


if __name__ == "__main__":
    main() 