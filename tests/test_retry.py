import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from core.retry import retry_with_backoff, _is_retryable


def test_is_retryable_connection_error():
    assert _is_retryable(ConnectionError("test")) is True
    assert _is_retryable(TimeoutError("test")) is True
    assert _is_retryable(ValueError("test")) is False
    assert _is_retryable(TypeError("test")) is False


def test_retry_sync_success():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def sync_func():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = sync_func()
    assert result == "ok"
    assert call_count == 1


def test_retry_sync_eventual_success():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def sync_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("fail")
        return "ok"

    result = sync_func()
    assert result == "ok"
    assert call_count == 3


def test_retry_sync_all_fail():
    @retry_with_backoff(max_retries=2, base_delay=0.01)
    def sync_func():
        raise ConnectionError("always fail")

    with pytest.raises(ConnectionError):
        sync_func()


def test_retry_non_retryable_not_retried():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def sync_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        sync_func()
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_async_success():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    async def async_func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("fail")
        return "ok"

    result = await async_func()
    assert result == "ok"
    assert call_count == 2
