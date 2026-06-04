"""LLM 基础设施测试（不实际调用 API）。

测试 LLM 调用链路：路由选择、参数验证、错误处理。
"""
import sys
import time
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    print("=== LLM 基础设施测试 ===\n")

    from core.config import settings
    print(f"LLM model: {settings.LLM_DEFAULT_MODEL}")
    print(f"API base: {settings.LLM_API_BASE}")
    print(f"API key configured: {bool(settings.LLM_API_KEY)}")
    print()

    # 测试 1: 模型路由选择
    print("=== Test 1: 模型路由 ===")
    from core.model_router import get_router, ModelRole, TASK_TO_ROLE
    from core.models import TaskType

    router = get_router()
    for task_type in [TaskType.PLAN, TaskType.WRITE, TaskType.REWRITE, TaskType.CHECK, TaskType.WORLD, TaskType.CHARACTER, TaskType.PLOT]:
        role = TASK_TO_ROLE.get(task_type, ModelRole.WRITER)
        model = router.select_model(role)
        print(f"  {task_type.value} -> {role.value} -> {model.name if model else 'None'}")
    print()

    # 测试 2: 路由统计
    print("=== Test 2: 路由统计 ===")
    stats = router.get_stats()
    print(f"Tracked models: {len(stats)}")
    for name, s in stats.items():
        print(f"  {name}: calls={s['total_calls']}, failures={s['total_failures']}, latency={s['avg_latency_ms']:.0f}ms")
    print()

    # 测试 3: 错误分类
    print("=== Test 3: 错误分类 ===")
    from core.retry import classify_error, ErrorType, is_retryable
    test_errors = [
        ("401 Unauthorized", ErrorType.AUTH, False),
        ("timeout occurred", ErrorType.TIMEOUT, True),
        ("429 rate limit", ErrorType.RATE_LIMIT, True),
        ("context length exceeded", ErrorType.CONTEXT_LENGTH, False),
        ("500 server error", ErrorType.SERVER_ERROR, True),
        ("connection refused", ErrorType.CONNECTION, True),
    ]
    for msg, expected_type, expected_retry in test_errors:
        exc = Exception(msg)
        actual_type = classify_error(exc)
        actual_retry = is_retryable(exc, type('cfg', (), {'non_retryable': {ErrorType.AUTH, ErrorType.NOT_FOUND, ErrorType.CONTENT_FILTER, ErrorType.INVALID_REQUEST, ErrorType.CONTEXT_LENGTH}})())
        status = "OK" if actual_type == expected_type and actual_retry == expected_retry else "FAIL"
        print(f"  [{status}] '{msg}' -> {actual_type.value} (retry={actual_retry})")
    print()

    # 测试 4: 模拟 LLM 调用 - 成功路径
    print("=== Test 4: 模拟成功调用 ===")
    from core.llm_router import call_llm, TaskType

    with patch("core.llm_router.litellm") as mock_litellm:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "这是测试响应"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        try:
            result = await call_llm(
                task_type=TaskType.WRITE,
                prompt="测试 prompt",
                temperature=0.7,
                max_tokens=100,
            )
            print(f"OK: {result}")
        except Exception as e:
            print(f"FAILED: {e}")
    print()

    # 测试 5: 模拟 LLM 调用 - 错误重试
    print("=== Test 5: 模拟超时重试 ===")
    with patch("core.llm_router.litellm") as mock_litellm:
        # 前两次超时，第三次成功
        success_response = AsyncMock()
        success_response.choices = [AsyncMock()]
        success_response.choices[0].message.content = "重试成功"
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("connection timeout")
            return success_response

        mock_litellm.acompletion = AsyncMock(side_effect=side_effect)

        try:
            result = await call_llm(
                task_type=TaskType.WRITE,
                prompt="测试",
                temperature=0.7,
                max_tokens=100,
            )
            print(f"OK: {result} (after {call_count} calls)")
        except Exception as e:
            print(f"FAILED after {call_count} calls: {e}")
    print()

    # 测试 6: 模拟 LLM 调用 - JSON 解析
    print("=== Test 6: 模拟 JSON 解析 ===")
    with patch("core.llm_router.litellm") as mock_litellm:
        # 返回带 markdown 代码块的 JSON
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = '```json\n{"name": "test", "value": 42}\n```'
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        try:
            result = await call_llm(
                task_type=TaskType.PLAN,
                prompt="测试",
                temperature=0.3,
                max_tokens=100,
                json_mode=True,
            )
            print(f"OK: {result}")
        except Exception as e:
            print(f"FAILED: {e}")
    print()

    # 测试 7: 模拟 LLM 调用 - 包含思考块
    print("=== Test 7: 模拟思考块剥离 ===")
    with patch("core.llm_router.litellm") as mock_litellm:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "<think>这是思考过程</think>这是实际输出"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        try:
            result = await call_llm(
                task_type=TaskType.WRITE,
                prompt="测试",
                temperature=0.7,
                max_tokens=100,
            )
            print(f"OK: {result}")
            if "思考" not in result and "实际输出" in result:
                print("PASSED: thinking block stripped")
        except Exception as e:
            print(f"FAILED: {e}")
    print()

    # 测试 8: 缓存
    print("=== Test 8: 缓存验证 ===")
    from core.cache import get_cache
    cache = get_cache()
    cache.clear()
    print(f"Cache enabled: {cache.enabled}")
    cache.set("test", "key1", "value1")
    print(f"Get: {cache.get('test', 'key1')}")
    print(f"Stats: {cache.stats()}")
    print()

    print("=== LLM 基础设施测试完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
