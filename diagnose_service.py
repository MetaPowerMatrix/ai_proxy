#!/usr/bin/env python3
"""MiniCPM 服务诊断工具"""

import requests
import time
import subprocess

def check_basic_service():
    """检查基础服务状态"""
    print("🔍 检查MiniCPM基础服务...")
    
    base_url = "http://localhost:32550"
    
    # 1. 健康检查
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"✅ 健康检查: {response.status_code}")
        return True
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False

def test_simple_completions():
    """测试最简单的completions请求"""
    print("📝 测试简单completions...")
    
    base_url = "http://localhost:32550"
    unique_uid = f"diag_{int(time.time() * 1000)}"
    
    try:
        headers = {"uid": unique_uid}
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "hi"},
            timeout=10
        )
        
        print(f"✅ Completions测试: {response.status_code}")
        if response.status_code != 200:
            print(f"响应: {response.text}")
        return response.status_code == 200
        
    except requests.exceptions.Timeout:
        print("❌ Completions测试超时")
        return False
    except Exception as e:
        print(f"❌ Completions测试失败: {e}")
        return False

def check_port_usage():
    """检查端口占用情况"""
    print("🔌 检查端口占用...")
    
    try:
        result = subprocess.run(['lsof', '-i', ':32550'], 
                              capture_output=True, text=True)
        if result.stdout:
            print("端口32550占用情况:")
            print(result.stdout)
        else:
            print("端口32550没有活跃连接")
    except:
        print("无法检查端口占用")

def main():
    print("=" * 50)
    print("MiniCPM 服务快速诊断")
    print("=" * 50)
    
    # 检查基础服务
    if not check_basic_service():
        print("\n❌ 基础服务不可用，请检查MiniCPM是否启动")
        return
    
    # 检查completions功能
    if not test_simple_completions():
        print("\n❌ Completions功能异常")
        check_port_usage()
        print("\n💡 建议解决方案:")
        print("1. 重启MiniCPM服务")
        print("2. 检查服务端日志")
        print("3. 确认模型是否正确加载")
        return
    
    print("\n✅ 基础服务功能正常")
    print("💡 音频处理问题可能是:")
    print("1. 音频处理模块异常")
    print("2. 音频文件格式问题") 
    print("3. 处理超时或资源不足")

if __name__ == "__main__":
    main() 