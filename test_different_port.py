 #!/usr/bin/env python3
"""测试不同端口的MiniCPM服务"""

import requests
import time

def test_port(port):
    """测试指定端口的服务"""
    print(f"🔍 测试端口 {port}...")
    
    base_url = f"http://localhost:{port}"
    unique_uid = f"port_test_{port}_{int(time.time() * 1000)}"
    
    try:
        # 健康检查
        health = requests.get(f"{base_url}/health", timeout=5)
        print(f"   健康检查: {health.status_code}")
        
        # 简单completions测试
        headers = {"uid": unique_uid}
        response = requests.post(
            f"{base_url}/api/v1/completions",
            headers=headers,
            json={"prompt": "hi"},
            timeout=10
        )
        
        print(f"   Completions: {response.status_code}")
        if response.status_code == 200:
            print(f"   ✅ 端口 {port} 正常工作!")
            return True
        else:
            print(f"   ❌ 端口 {port} 有问题: {response.text[:100]}")
            
    except Exception as e:
        print(f"   ❌ 端口 {port} 不可用: {e}")
    
    return False

def main():
    print("=" * 50)
    print("测试不同端口的MiniCPM服务")
    print("=" * 50)
    
    # 常见的端口
    ports = [32550, 8000, 8080, 7860, 5000]
    
    working_ports = []
    for port in ports:
        if test_port(port):
            working_ports.append(port)
    
    if working_ports:
        print(f"\n✅ 可用端口: {working_ports}")
        print("💡 可以尝试修改客户端连接到这些端口")
    else:
        print("\n❌ 所有常见端口都不可用")
        print("💡 建议重启服务或检查服务配置")

if __name__ == "__main__":
    main()