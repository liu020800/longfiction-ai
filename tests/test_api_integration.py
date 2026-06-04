"""API 端点集成测试。

直接调用 FastAPI 应用的路由，无需启动服务器。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
import time
from fastapi.testclient import TestClient


def main():
    print("=== Loading FastAPI app ===")
    from api.main import app
    client = TestClient(app)
    print("OK\n")

    # 测试 1: 健康检查
    print("=== Test 1: GET /api/health ===")
    r = client.get("/api/health")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Name: {data.get('name')}")
        print(f"Version: {data.get('version')}")
        print(f"LLM configured: {data.get('llm_configured')}")
        print(f"Models: {list(data.get('models', {}).keys())}")
    print()

    # 测试 2: 登录
    print("=== Test 2: POST /api/auth/login ===")
    r = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "admin123456"
    })
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        # API 响应可能用 access_token 或 token
        token = data.get("access_token", "") or data.get("token", "")
        print(f"Token length: {len(token)}")
        print(f"User: {data.get('user', {}).get('username')}")
    else:
        print(f"Error: {r.text[:300]}")
        token = ""
    print()

    if not token:
        print("Skipping authenticated tests (login failed)")
        return

    headers = {"Authorization": f"Bearer {token}"}

    # 测试 3: 获取当前用户
    print("=== Test 3: GET /api/auth/me ===")
    r = client.get("/api/auth/me", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Username: {data.get('username')}")
        print(f"Role: {data.get('role')}")
        print(f"Balance: {data.get('balance')}")
    print()

    # 测试 4: 列出项目
    print("=== Test 4: GET /api/db/projects ===")
    r = client.get("/api/db/projects", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print(f"Project count: {len(data)}")
            for p in data[:3]:
                print(f"  - {p.get('id')}: {p.get('title', 'No title')}")
        else:
            print(f"Response: {str(data)[:200]}")
    print()

    # 测试 5: 获取已存在项目
    print("=== Test 5: GET /api/projects ===")
    r = client.get("/api/projects", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print(f"Project count: {len(data)}")
    print()

    # 测试 6: 风格库
    print("=== Test 6: GET /api/styles ===")
    r = client.get("/api/styles", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print(f"Style count: {len(data)}")
            for s in data[:5]:
                print(f"  - {s.get('name', s)}")
    print()

    # 测试 7: 体裁模板
    print("=== Test 7: GET /api/templates ===")
    r = client.get("/api/templates")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print(f"Template count: {len(data)}")
            for t in data[:3]:
                print(f"  - {t.get('name', t)}")
    print()

    # 测试 8: 静态资源（前端）
    print("=== Test 8: GET / (frontend) ===")
    r = client.get("/")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print(f"Content type: {r.headers.get('content-type', 'unknown')[:50]}")
        print(f"Body length: {len(r.content)} bytes")
    print()

    print("=== API 集成测试完成 ===")


if __name__ == "__main__":
    main()
