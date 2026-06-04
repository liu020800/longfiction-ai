"""测试 core.retry 模块。"""
import asyncio
import pytest

from core.retry import (
    RetryConfig,
    RetryStrategy,
    ErrorType,
    classify_error,
    is_retryable,
    calculate_delay,
    retry_async,
    retryable,
    DEFAULT_RETRY_CONFIG,
    FAST_TEST_RETRY_CONFIG,
)


class TestErrorClassification:
    def test_classify_timeout(self):
        assert classify_error(TimeoutError("Request timeout")) == ErrorType.TIMEOUT
        assert classify_error(Exception("Operation timed out")) == ErrorType.TIMEOUT

    def test_classify_connection(self):
        assert classify_error(ConnectionError("connection aborted")) == ErrorType.CONNECTION
        assert classify_error(Exception("network error")) == ErrorType.CONNECTION

    def test_classify_rate_limit(self):
        assert classify_error(Exception("429 Too Many Requests")) == ErrorType.RATE_LIMIT
        assert classify_error(Exception("Rate limit exceeded")) == ErrorType.RATE_LIMIT

    def test_classify_auth(self):
        assert classify_error(Exception("401 Unauthorized")) == ErrorType.AUTH
        assert classify_error(Exception("Invalid API key")) == ErrorType.AUTH

    def test_classify_context_length(self):
        assert classify_error(Exception("context length exceeded")) == ErrorType.CONTEXT_LENGTH
        assert classify_error(Exception("maximum context")) == ErrorType.CONTEXT_LENGTH

    def test_classify_unknown(self):
        assert classify_error(Exception("some random error")) == ErrorType.UNKNOWN


class TestIsRetryable:
    def test_auth_not_retryable(self):
        config = RetryConfig()
        assert is_retryable(Exception("401 Unauthorized"), config) is False

    def test_context_length_not_retryable(self):
        config = RetryConfig()
        assert is_retryable(Exception("context length exceeded"), config) is False

    def test_timeout_retryable(self):
        config = RetryConfig()
        assert is_retryable(TimeoutError("timeout"), config) is True

    def test_rate_limit_retryable(self):
        config = RetryConfig()
        assert is_retryable(Exception("429 rate limit"), config) is True


class TestDelayCalculation:
    def test_exponential_growth(self):
        config = RetryConfig(strategy=RetryStrategy.EXPONENTIAL, initial_delay=1.0, backoff_multiplier=2.0, max_delay=100.0)
        assert calculate_delay(0, config) == 1.0
        assert calculate_delay(1, config) == 2.0
        assert calculate_delay(2, config) == 4.0
        assert calculate_delay(3, config) == 8.0

    def test_max_delay_cap(self):
        config = RetryConfig(strategy=RetryStrategy.EXPONENTIAL, initial_delay=1.0, backoff_multiplier=10.0, max_delay=50.0)
        assert calculate_delay(5, config) == 50.0

    def test_constant_strategy(self):
        config = RetryConfig(strategy=RetryStrategy.CONSTANT, initial_delay=2.0)
        assert calculate_delay(0, config) == 2.0
        assert calculate_delay(5, config) == 2.0


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        call_count = 0
        async def success_func():
            nonlocal call_count
            call_count += 1
            return "ok"
        result = await retry_async(success_func, config=FAST_TEST_RETRY_CONFIG)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        call_count = 0
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("request timeout occurred")
            return "ok"
        config = RetryConfig(max_retries=3, initial_delay=0.01, max_delay=0.1)
        result = await retry_async(flaky_func, config=config)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self):
        call_count = 0
        async def auth_error_func():
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized")
        with pytest.raises(Exception, match="401"):
            await retry_async(auth_error_func, config=FAST_TEST_RETRY_CONFIG)
        assert call_count == 1  # 第一次就放弃

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        call_count = 0
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timeout")
        with pytest.raises(TimeoutError):
            await retry_async(always_fail, config=RetryConfig(max_retries=2, initial_delay=0.01, max_delay=0.1))
        assert call_count == 3  # 1 + 2 retries


class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_decorator(self):
        call_count = 0
        @retryable(RetryConfig(max_retries=2, initial_delay=0.01))
        async def my_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("timeout")
            return 42
        result = await my_func()
        assert result == 42
        assert call_count == 2
