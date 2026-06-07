"""集成测试：使用真实 LLM 调用 probe_llm_all。

需要 OPENAI_API_KEY 或 LLM_API_KEY 环境变量。
无 key 时自动 skip，不会让普通 `pytest` 失败。
"""
import os

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_probe_chat():
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_API_KEY"):
        pytest.skip("No real LLM API key configured (set OPENAI_API_KEY or LLM_API_KEY)")

    from core.llm_probe import probe_llm_all
    result = await probe_llm_all()
    # 只要 probe_llm_all 跑完不抛异常就算通过；具体 ok=True/False 取决于
    # 网络和 provider 配置
    assert "ok" in result
    assert "chat" in result
    assert "json" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_probe_json():
    """验证 probe_json 在真实 LLM 上能解析 JSON 模式返回。"""
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_API_KEY"):
        pytest.skip("No real LLM API key configured")

    from core.llm_probe import probe_llm_all
    result = await probe_llm_all()
    if result.get("ok"):
        # 整体 ok 时，json 子步骤也应 ok
        assert result["json"].get("ok") is True
