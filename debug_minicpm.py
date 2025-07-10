#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCPM 服务调试工具
用于诊断连接问题和服务状态
"""

import requests
import time
import sys
from minicpm_client import MiniCPMClient


def check_service_connectivity(base_url):
    """检查服务连接性"""
    print(f"📡 检查服务连接性: {base_url}")
    
    # 1. 基本连接测试
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"✅ 健康检查: {response.status_code}")
        if response.status_code == 200:
            print(f"   响应内容: {response.text[:200]}")
        else:
            print(f"   响应内容: {response.text}")
    except requests.exceptions.Timeout:
        print("❌ 健康检查超时 (5秒)")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ 连接错误 - 服务可能未启动")
        return False
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False
    
    # 2. 测试其他端点
    endpoints = [
        "/api/v1/stream",
        "/api/v1/completions", 
        "/init_options"
    ]
    
    for endpoint in endpoints:
        try:
            # 使用HEAD请求测试端点是否存在
            response = requests.head(f"{base_url}{endpoint}", timeout=5)
            print(f"🔍 端点 {endpoint}: {response.status_code}")
        except Exception as e:
            print(f"❌ 端点 {endpoint} 测试失败: {e}")
    
    return True


def test_minicpm_client():
    """测试MiniCPM客户端"""
    print("\n🔧 测试MiniCPM客户端...")
    
    client = MiniCPMClient()
    
    # 1. 测试服务状态
    print("1️⃣ 测试服务状态检查...")
    status_response = client.check_service_status()
    if status_response is None:
        print("❌ 服务状态检查失败")
        return False
    else:
        print(f"✅ 服务状态检查成功: {status_response.status_code}")
    
    # 2. 测试简单请求（不需要音频文件）
    print("2️⃣ 测试简单completions请求...")
    try:
        response = client.session.post(
            f"{client.base_url}/api/v1/completions",
            headers={"uid": client.uid},
            json={"prompt": "hello"},
            timeout=10
        )
        print(f"✅ Completions请求: {response.status_code}")
        if response.status_code != 200:
            print(f"   响应内容: {response.text}")
    except requests.exceptions.Timeout:
        print("❌ Completions请求超时 (10秒)")
        return False
    except Exception as e:
        print(f"❌ Completions请求失败: {e}")
        return False
    
    return True


def diagnose_network_issues():
    """诊断网络问题"""
    print("\n🌐 网络诊断...")
    
    # 测试本地连接
    import socket
    
    host = "localhost"
    port = 32550
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"✅ 端口 {host}:{port} 可连接")
        else:
            print(f"❌ 端口 {host}:{port} 不可连接")
            print("   可能原因:")
            print("   - MiniCPM服务未启动")
            print("   - 端口被其他程序占用")
            print("   - 防火墙阻止连接")
            return False
    except Exception as e:
        print(f"❌ 网络连接测试失败: {e}")
        return False
    
    return True


def main():
    print("=" * 60)
    print("MiniCPM 服务调试工具")
    print("=" * 60)
    
    base_url = "http://localhost:32550"
    
    # 1. 网络诊断
    if not diagnose_network_issues():
        print("\n💡 建议:")
        print("   1. 检查MiniCPM服务是否已启动")
        print("   2. 检查端口32550是否被占用")
        print("   3. 尝试重启MiniCPM服务")
        sys.exit(1)
    
    # 2. 服务连接测试
    if not check_service_connectivity(base_url):
        print("\n💡 建议:")
        print("   1. 确认MiniCPM服务正在运行")
        print("   2. 检查服务配置和日志")
        print("   3. 尝试直接访问健康检查端点")
        sys.exit(1)
    
    # 3. 客户端测试
    if not test_minicpm_client():
        print("\n💡 建议:")
        print("   1. 检查客户端配置")
        print("   2. 查看服务端日志获取更多信息")
        print("   3. 尝试减少请求超时时间")
        sys.exit(1)
    
    print("\n✅ 所有测试通过！MiniCPM服务运行正常")
    print("\n🔧 如果音频请求仍然卡住，可能的原因:")
    print("   1. 音频数据过大导致传输慢")
    print("   2. 服务端处理音频时间过长")
    print("   3. 建议增加timeout时间或检查音频文件大小")


if __name__ == "__main__":
    main() 