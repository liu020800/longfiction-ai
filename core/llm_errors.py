"""LLM 异常分类。

将各类 LLM 调用异常归一化为 `(retryable, fatal, code, user_message)`，供重试与降级逻辑使用。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMErrorInfo:
    """LLM 异常归类结果。"""
    retryable: bool
    fatal: bool
    code: str
    user_message: str


def classify_llm_exception(exc: Exception) -> LLMErrorInfo:
    """根据异常信息分类 LLM 调用错误。

    分类规则基于错误信息字符串匹配，覆盖：
    - 401/403 鉴权错误（不重试）
    - 404 模型不存在（不重试）
    - 上下文超限（不重试）
    - 429/限流（重试）
    - timeout/connection/provider_unavailable（重试）
    - 其它（按可重试处理）
    """
    msg = str(exc)
    low = msg.lower()

    if "401" in msg or "unauthorized" in low or "invalid api key" in low:
        return LLMErrorInfo(
            retryable=False,
            fatal=True,
            code="auth_error",
            user_message="API Key 无效或已被服务端拒绝，请更换有效 Key。",
        )

    if "403" in msg or "forbidden" in low:
        return LLMErrorInfo(
            retryable=False,
            fatal=True,
            code="permission_error",
            user_message="API Key 权限不足，或当前账号无权调用该模型。",
        )

    if "model" in low and ("not found" in low or "unknown" in low):
        return LLMErrorInfo(
            retryable=False,
            fatal=True,
            code="model_not_found",
            user_message="模型名不存在或供应商前缀不正确，请检查 LLM 模型配置。",
        )

    if (
        "context length" in low
        or "maximum context" in low
        or "too many tokens" in low
        or "context_length_exceeded" in low
    ):
        return LLMErrorInfo(
            retryable=False,
            fatal=True,
            code="context_too_long",
            user_message="上下文或 max_tokens 超出模型限制，需要降低章节数、字数或 prompt 长度。",
        )

    if "429" in msg or "rate limit" in low or "too many requests" in low:
        return LLMErrorInfo(
            retryable=True,
            fatal=False,
            code="rate_limited",
            user_message="模型服务限流，稍后自动重试。",
        )

    if "timeout" in low or "timed out" in low:
        return LLMErrorInfo(
            retryable=True,
            fatal=False,
            code="timeout",
            user_message="模型请求超时，正在重试或切换备用模型。",
        )

    if "502" in msg or "503" in msg or "504" in msg or "bad gateway" in low or "service unavailable" in low:
        return LLMErrorInfo(
            retryable=True,
            fatal=False,
            code="provider_unavailable",
            user_message="模型供应商暂时不可用，正在重试或切换备用模型。",
        )

    if "connection" in low or "connect" in low or "network" in low:
        return LLMErrorInfo(
            retryable=True,
            fatal=False,
            code="connection_error",
            user_message="无法连接模型服务，正在重试。",
        )

    if "json" in low and ("decode" in low or "parse" in low or "expecting value" in low):
        return LLMErrorInfo(
            retryable=False,
            fatal=False,
            code="json_error",
            user_message="模型返回内容无法解析为 JSON。",
        )

    return LLMErrorInfo(
        retryable=True,
        fatal=False,
        code="unknown",
        user_message=msg[:300] or "未知 LLM 错误",
    )
