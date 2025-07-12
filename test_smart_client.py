#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试智能MiniCPM客户端
基于Stream响应智能决定处理流程
"""

import os
import time
from minicpm_client import MiniCPMClient

def on_audio_done(audio_chunks):
    pass

def on_text_done(text_chunks):
    pass

def test_chunked_audio_processing():
    """测试分片音频处理"""
    print("\n" + "=" * 70)
    print("分片音频处理测试 - 20片段发送")
    print("=" * 70)
    
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
    client.init_with_adaptive_vad(reference_audio_file)
    client.start_completions_listener(on_audio_done=on_audio_done, on_text_done=on_text_done)

    # 分片处理
    chunks = client.split_audio_into_chunks(audio_file, num_chunks=20)
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
    
    response2 = client.send_completions_request()
    print(f"completions响应头: {dict(response2.headers)}")
    time.sleep(20)
    # 如果需要获取最终结果，可以调用completions
    # if successful_chunks > 0:
    #     print(f"\n4️⃣ 获取最终处理结果...")
    #     try:
    #         final_audio_chunks, final_text = client.stream_audio_processing()
            
    #         if final_audio_chunks or final_text:
    #             print(f"✅ 获取到最终结果:")
    #             print(f"   音频片段数: {len(final_audio_chunks) if final_audio_chunks else 0}")
    #             print(f"   文本长度: {len(final_text) if final_text else 0}")
    #             print(f"   文本内容: {final_text if final_text else '无'}")
                
    #             # 保存最终音频
    #             if final_audio_chunks:
    #                 try:
    #                     from minicpm_client import merge_pcm_chunks, save_pcm_as_wav
    #                     merged_pcm = merge_pcm_chunks([chunk[0] for chunk in final_audio_chunks])
    #                     if merged_pcm is not None:
    #                         output_file = "output_chunked.wav"
    #                         save_pcm_as_wav(merged_pcm, 16000, 1, output_file)
    #                         print(f"   💾 最终音频已保存为 {output_file}")
    #                 except Exception as e:
    #                     print(f"   ⚠️ 保存最终音频失败: {e}")
    #         else:
    #             print(f"⚠️ 未获取到最终结果")
                
    #     except Exception as e:
    #         print(f"❌ 获取最终结果失败: {e}")
    
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