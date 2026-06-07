"""LLM 可用性探针。

在用户开始任何生成任务前，验证 LLM 服务是否真的可用，并对错误做明确分类。
通过真实调用 `core.llm_router.call_llm()` 走生产路径，确保探针结果与实际行为一致。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from core.config import settings
from core.llm_errors import classify_llm_exception
from core.llm_router import call_llm
from core.models import TaskType


@dataclass
class LLMProbeResult:
    """单次探针结果。"""
    ok: bool
    stage: str
    latency_ms: int = 0
    model: str = ""
    api_base: str = ""
    error_type: str = ""
    error: str = ""
    details: Optional[dict[str, Any]] = None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _strip_code_fence_for_chat(text: str) -> str:
    """剥离 markdown 围栏用于 chat 响应比较。"""
    import re
    m = re.search(r"```(?:[a-zA-Z]*)\s*(.*?)\s*```", text, re.S)
    if m:
        return m.group(1).strip()
    return text.strip()


async def probe_chat() -> LLMProbeResult:
    """发送"只回复 OK"指令，校验 chat 链路。"""
    start = time.time()
    model_name = settings.LLM_CHECK_MODEL or settings.LLM_DEFAULT_MODEL
    api_base = settings.LLM_API_BASE

    if not settings.LLM_API_KEY:
        return LLMProbeResult(
            ok=False,
            stage="chat",
            model=model_name,
            api_base=api_base,
            error_type="missing_api_key",
            error="未配置 OPENAI_API_KEY 或 LLM_API_KEY",
        )

    try:
        raw = await call_llm(
            task_type=TaskType.CHECK,
            prompt="只回复 OK，不要解释，不要任何标点。",
            system="你是连通性测试助手。",
            temperature=0.1,
            max_tokens=10,
            json_mode=False,
        )
        latency = int((time.time() - start) * 1000)
        text = _strip_code_fence_for_chat(str(raw))
        ok = "OK" in text.upper()
        return LLMProbeResult(
            ok=ok,
            stage="chat",
            latency_ms=latency,
            model=model_name,
            api_base=api_base,
            error_type="" if ok else "chat_mismatch",
            error="" if ok else f"模型未按预期回复 OK，实际响应：{text[:80]}",
            details={"response": text[:100]},
        )
    except Exception as exc:
        info = classify_llm_exception(exc)
        return LLMProbeResult(
            ok=False,
            stage="chat",
            latency_ms=int((time.time() - start) * 1000),
            model=model_name,
            api_base=api_base,
            error_type=info.code,
            error=info.user_message,
        )


async def probe_json() -> LLMProbeResult:
    """发送"返回严格 JSON"指令，校验 JSON 链路。"""
    start = time.time()
    model_name = settings.LLM_CHECK_MODEL or settings.LLM_DEFAULT_MODEL
    api_base = settings.LLM_API_BASE

    if not settings.LLM_API_KEY:
        return LLMProbeResult(
            ok=False,
            stage="json",
            model=model_name,
            api_base=api_base,
            error_type="missing_api_key",
            error="未配置 OPENAI_API_KEY 或 LLM_API_KEY",
        )

    try:
        result = await call_llm(
            task_type=TaskType.CHECK,
            prompt='返回严格 JSON：{"ok": true, "msg": "pong"}',
            system="你只能输出 JSON，不要 Markdown，不要解释。",
            temperature=0.1,
            max_tokens=100,
            json_mode=True,
        )
        latency = int((time.time() - start) * 1000)
        ok = isinstance(result, dict) and result.get("ok") is True
        return LLMProbeResult(
            ok=ok,
            stage="json",
            latency_ms=latency,
            model=model_name,
            api_base=api_base,
            error_type="" if ok else "json_error",
            error="" if ok else f"模型未返回预期的 JSON 对象：{str(result)[:120]}",
            details={"response": result if isinstance(result, (dict, list)) else str(result)[:200]},
        )
    except Exception as exc:
        info = classify_llm_exception(exc)
        return LLMProbeResult(
            ok=False,
            stage="json",
            latency_ms=int((time.time() - start) * 1000),
            model=model_name,
            api_base=api_base,
            error_type=info.code,
            error=info.user_message,
        )


async def probe_llm_all() -> dict[str, Any]:
    """完整 LLM 可用性校验：先 chat 再 json，任一失败立即返回。"""
    if not settings.LLM_API_KEY:
        return {
            "ok": False,
            "error_type": "missing_api_key",
            "error": "未配置 OPENAI_API_KEY 或 LLM_API_KEY",
            "chat": None,
            "json": None,
        }

    chat = await probe_chat()
    if not chat.ok:
        return {
            "ok": False,
            "error_type": chat.error_type,
            "error": chat.error,
            "chat": chat.model_dump(),
            "json": None,
        }

    json_result = await probe_json()
    return {
        "ok": chat.ok and json_result.ok,
        "error_type": "" if json_result.ok else json_result.error_type,
        "error": "" if json_result.ok else json_result.error,
        "chat": chat.model_dump(),
        "json": json_result.model_dump(),
    }
