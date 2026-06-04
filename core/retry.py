import asyncio
import functools
import logging
import time
from typing import Callable, Any

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    exc_name = type(exc).__name__
    retryable_names = {
        "ConnectionError", "TimeoutError", "ConnectTimeout",
        "ReadTimeout", "WriteTimeout", "PoolError",
        "APIConnectionError", "APITimeoutError", "RateLimitError",
        "ServiceUnavailableError", "InternalServerError",
    }
    return exc_name in retryable_names


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable_check: Callable[[Exception], bool] | None = None,
):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> Any:
                last_exc = None
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        check = retryable_check or _is_retryable
                        if not check(exc):
                            raise
                        last_exc = exc
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(
                                f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                                f"after {delay:.1f}s: {type(exc).__name__}: {exc}"
                            )
                            await asyncio.sleep(delay)
                        else:
                            logger.error(
                                f"All {max_retries} retries exhausted for {func.__name__}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                raise last_exc
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs) -> Any:
                last_exc = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as exc:
                        check = retryable_check or _is_retryable
                        if not check(exc):
                            raise
                        last_exc = exc
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(
                                f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                                f"after {delay:.1f}s: {type(exc).__name__}: {exc}"
                            )
                            time.sleep(delay)
                        else:
                            logger.error(
                                f"All {max_retries} retries exhausted for {func.__name__}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                raise last_exc
            return sync_wrapper
    return decorator
