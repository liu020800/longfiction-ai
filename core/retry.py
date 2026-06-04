"""LLM 调用重试机制。

提供指数退避、可重试错误识别、降级策略。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


class RetryStrategy(str, Enum):
    """重试策略。"""
    EXPONENTIAL = "exponential"  # 指数退避
    LINEAR = "linear"            # 线性退避
    CONSTANT = "constant"        # 固定间隔
    JITTER = "jitter"            # 随机抖动


class ErrorType(str, Enum):
    """错误类型分类。"""
    # 可重试
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    OVERLOADED = "overloaded"

    # 不可重试
    AUTH = "auth"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONTENT_FILTER = "content_filter"
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"


# 错误关键字 -> 错误类型映射
ERROR_KEYWORDS: dict[ErrorType, list[str]] = {
    ErrorType.TIMEOUT: ["timeout", "timed out", "deadline exceeded"],
    ErrorType.CONNECTION: [
        "connection", "network", "eof", "reset", "broken pipe",
        "errno 10054", "winerror 10054", "connection aborted",
    ],
    ErrorType.RATE_LIMIT: [
        "rate limit", "ratelimit", "rate_limit", "429",
        "too many requests", "quota exceeded",
    ],
    ErrorType.SERVER_ERROR: [
        "500", "502", "503", "504", "internal server error",
        "bad gateway", "service unavailable", "gateway timeout",
        "upstream", "backend", "unavailable",
    ],
    ErrorType.OVERLOADED: [
        "overloaded", "too busy", "high load", "capacity",
    ],
    ErrorType.AUTH: [
        "401", "403", "unauthorized", "forbidden", "invalid api key",
        "authentication", "permission denied", "api key",
    ],
    ErrorType.INVALID_REQUEST: [
        "400", "bad request", "invalid parameter", "invalid_argument",
        "validation error", "schema", "malformed",
    ],
    ErrorType.NOT_FOUND: [
        "404", "not found", "model not found", "does not exist",
    ],
    ErrorType.CONTENT_FILTER: [
        "content filter", "content_policy", "safety", "harmful",
        "blocked", "violates", "inappropriate",
    ],
    ErrorType.CONTEXT_LENGTH: [
        "context length", "context_length", "maximum context",
        "too long", "token limit", "max_tokens",
    ],
}


@dataclass
class RetryConfig:
    """重试配置。"""
    max_retries: int = 3
    initial_delay: float = 1.0          # 初始延迟（秒）
    max_delay: float = 30.0             # 最大延迟（秒）
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    backoff_multiplier: float = 2.0     # 退避倍数
    jitter_range: float = 0.5           # 抖动范围 [0, 1)
    # 不重试的错误类型
    non_retryable: set[ErrorType] = field(default_factory=lambda: {
        ErrorType.AUTH,
        ErrorType.NOT_FOUND,
        ErrorType.CONTENT_FILTER,
        ErrorType.INVALID_REQUEST,
        ErrorType.CONTEXT_LENGTH,
    })


def classify_error(exc: BaseException) -> ErrorType:
    """根据异常信息分类错误类型。"""
    msg = (str(exc) or "").lower()
    for err_type, keywords in ERROR_KEYWORDS.items():
        for kw in keywords:
            if kw in msg:
                return err_type
    return ErrorType.UNKNOWN


def is_retryable(exc: BaseException, config: RetryConfig) -> bool:
    """判断异常是否可重试。"""
    err_type = classify_error(exc)
    if err_type in config.non_retryable:
        return False
    # 未知错误保守地视为可重试
    return True


def calculate_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """根据策略计算延迟时间。"""
    if config.strategy == RetryStrategy.EXPONENTIAL:
        delay = config.initial_delay * (config.backoff_multiplier ** attempt)
    elif config.strategy == RetryStrategy.LINEAR:
        delay = config.initial_delay * (attempt + 1)
    elif config.strategy == RetryStrategy.CONSTANT:
        delay = config.initial_delay
    else:  # JITTER
        delay = config.initial_delay * (config.backoff_multiplier ** attempt)
        delay = delay * (1 + random.uniform(-config.jitter_range, config.jitter_range))
    return min(delay, config.max_delay)


@dataclass
class RetryResult:
    """重试结果。"""
    success: bool
    value: Any = None
    error: Optional[BaseException] = None
    attempts: int = 0
    total_time: float = 0.0
    error_history: list[Tuple[int, ErrorType, str]] = field(default_factory=list)


async def retry_async(
    func: Callable[..., Awaitable[Any]],
    *args,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    **kwargs,
) -> Any:
    """异步函数重试装饰器/包装器。

    Args:
        func: 异步函数
        config: 重试配置
        on_retry: 重试时的回调（attempt, exception, delay）

    Returns:
        函数返回值

    Raises:
        最后一次尝试的异常（如果达到最大重试次数）
    """
    cfg = config or RetryConfig()
    last_exc: Optional[BaseException] = None
    start = time.monotonic()

    for attempt in range(cfg.max_retries + 1):
        try:
            value = await func(*args, **kwargs)
            return value
        except Exception as e:
            last_exc = e
            err_type = classify_error(e)
            logger.warning(
                f"LLM call failed (attempt {attempt + 1}/{cfg.max_retries + 1}): "
                f"[{err_type.value}] {e}"
            )

            if attempt >= cfg.max_retries:
                break

            if not is_retryable(e, cfg):
                logger.info(f"Error type {err_type.value} is not retryable, aborting")
                break

            delay = calculate_delay(attempt, cfg)
            if on_retry:
                try:
                    on_retry(attempt, e, delay)
                except Exception:
                    pass
            logger.info(f"Retrying in {delay:.2f}s...")
            await asyncio.sleep(delay)

    # 所有重试都失败
    total = time.monotonic() - start
    logger.error(f"LLM call failed after {cfg.max_retries + 1} attempts ({total:.2f}s)")
    assert last_exc is not None
    raise last_exc


def retryable(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
):
    """装饰器：标记异步函数为可重试。

    Usage:
        @retryable(RetryConfig(max_retries=3))
        async def call_llm(...):
            ...
    """
    cfg = config or RetryConfig()

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(func, *args, config=cfg, on_retry=on_retry, **kwargs)
        return wrapper
    return decorator


# 默认重试配置实例
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    initial_delay=1.0,
    max_delay=30.0,
    strategy=RetryStrategy.EXPONENTIAL,
    backoff_multiplier=2.0,
)


# 快速测试模式：减少重试次数
FAST_TEST_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    initial_delay=0.5,
    max_delay=5.0,
    strategy=RetryStrategy.CONSTANT,
)


# 向后兼容：旧 API 的别名
async def retry_with_backoff(
    func: Callable[..., Awaitable[Any]],
    *args,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs,
) -> Any:
    """向后兼容的重试函数。

    使用 retry_async 实现，提供 max_retries/initial_delay/max_delay 接口。
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
    )
    return await retry_async(func, *args, config=config, **kwargs)
