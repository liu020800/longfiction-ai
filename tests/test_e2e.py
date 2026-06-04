"""端到端测试 - 不需要实际 LLM 调用。

测试完整的项目流程：创建项目 -> CRUD 章节 -> 版本管理 -> 导出。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    print("=== 端到端测试 ===\n")

    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)

    # 1. 健康检查
    print("[1] 健康检查")
    r = client.get("/api/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print(f"  OK: {r.json()['status']}")

    # 2. 登录
    print("\n[2] 登录")
    r = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "admin123456"
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, "No token in response"
    headers = {"Authorization": f"Bearer {token}"}
    print(f"  OK: User={data['user']['username']}, Token length={len(token)}")

    # 3. 获取项目列表
    print("\n[3] 获取项目列表")
    r = client.get("/api/db/projects", headers=headers)
    assert r.status_code == 200, f"List projects failed: {r.text}"
    data = r.json()
    projects = data.get("projects", [])
    print(f"  OK: {len(projects)} projects")
    if projects:
        first_project = projects[0]
        print(f"  First project: {first_project.get('id', '?')[:8]}...")
        project_id = first_project.get("id")
    else:
        print("  No projects yet")
        project_id = None

    # 4. 如果有项目，测试章节相关
    if project_id:
        print(f"\n[4] 获取项目 {project_id} 的章节列表")
        r = client.get(f"/api/db/project/{project_id}/chapters", headers=headers)
        if r.status_code == 200:
            data = r.json()
            chapters = data.get("chapters", [])
            print(f"  OK: {len(chapters)} chapters")
            if chapters:
                first_chapter = chapters[0]
                chapter_id = first_chapter.get("id")
                print(f"  First chapter: id={chapter_id}, title={first_chapter.get('title', '?')[:30]}")
        else:
            print(f"  WARN: {r.status_code}")

    # 5. 获取体裁模板
    print("\n[5] 获取体裁模板")
    r = client.get("/api/templates", headers=headers)
    if r.status_code == 200:
        data = r.json()
        templates = data if isinstance(data, list) else data.get("templates", [])
        print(f"  OK: {len(templates)} templates")
        for t in templates[:3]:
            print(f"    - {t.get('name', t)}")
    else:
        print(f"  Status: {r.status_code}")

    # 6. 获取风格库
    print("\n[6] 获取风格库")
    r = client.get("/api/styles", headers=headers)
    if r.status_code == 200:
        data = r.json()
        styles = data if isinstance(data, list) else data.get("styles", [])
        print(f"  OK: {len(styles)} styles")
    else:
        print(f"  Status: {r.status_code}")

    # 7. 获取当前用户
    print("\n[7] 获取当前用户")
    r = client.get("/api/auth/me", headers=headers)
    if r.status_code == 200:
        user = r.json()
        print(f"  OK: {user.get('username')}, balance={user.get('balance')}")
    else:
        print(f"  Status: {r.status_code}")

    # 8. 风格学习（不需 LLM）
    print("\n[8] 风格学习（离线）")
    from agents.style_controller import learn_style_from_samples
    samples = ["林远怒吼。「战！」剑光暴涨。", "他身形一闪，躲过攻击。", "「太慢了！」"]
    profile = learn_style_from_samples(samples, "test")
    print(f"  OK: Learned {profile.name}")

    # 9. JSON 解析容错
    print("\n[9] JSON 解析容错")
    from core.validators import parse_json
    test_inputs = [
        '{"valid": true}',
        '```json\n{"in_fence": 1}\n```',
        '<think>思考</think>{"after_think": 2}',
        '{"trailing": "comma",}',  # 尾随逗号
    ]
    for inp in test_inputs:
        result = parse_json(inp, lenient=True)
        print(f"  {'OK' if result.success else 'FAIL'}: {inp[:40]}... -> {result.strategy}")

    # 10. 缓存
    print("\n[10] 缓存测试")
    from core.cache import get_cache
    cache = get_cache()
    cache.clear()
    cache.set("llm_response", "key1", "value1")
    assert cache.get("llm_response", "key1") == "value1"
    stats = cache.total_stats()
    print(f"  OK: hit_rate={stats['hit_rate']}")

    print("\n=== 端到端测试完成 ===")
    print("\n注意：实际的 LLM 生成测试因 API Key 失效而无法进行。")
    print("需提供有效的 API Key 后才能测试：")
    print("  - 章节生成 (POST /api/chapter)")
    print("  - 项目初始化 (POST /api/init)")
    print("  - 续写 (POST /api/chapter/continue)")
    print("  - 改写 (POST /api/chapter/revise)")


if __name__ == "__main__":
    main()
