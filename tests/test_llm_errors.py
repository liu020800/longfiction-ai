"""测试 core.llm_errors.classify_llm_exception 对各类异常字符串的归类。"""
import pytest

from core.llm_errors import LLMErrorInfo, classify_llm_exception


def _err(msg: str) -> Exception:
    return Exception(msg)


class TestClassifyLlmException:
    def test_returns_llmerrorinfo_dataclass(self):
        info = classify_llm_exception(_err("some random error"))
        assert isinstance(info, LLMErrorInfo)
        assert isinstance(info.retryable, bool)
        assert isinstance(info.fatal, bool)
        assert isinstance(info.code, str)
        assert isinstance(info.user_message, str)

    # ---- 401 / auth ----
    def test_401_is_auth_error(self):
        info = classify_llm_exception(_err("401 Unauthorized"))
        assert info.code == "auth_error"
        assert info.fatal is True
        assert info.retryable is False

    def test_unauthorized_keyword_is_auth_error(self):
        info = classify_llm_exception(_err("unauthorized access"))
        assert info.code == "auth_error"

    def test_invalid_api_key_phrase(self):
        info = classify_llm_exception(_err("Invalid API Key provided"))
        assert info.code == "auth_error"

    # ---- 403 / permission ----
    def test_403_is_permission_error(self):
        info = classify_llm_exception(_err("403 Forbidden"))
        assert info.code == "permission_error"
        assert info.fatal is True

    def test_forbidden_keyword(self):
        info = classify_llm_exception(_err("Forbidden: insufficient scope"))
        assert info.code == "permission_error"

    # ---- 404 / model not found ----
    def test_model_not_found(self):
        info = classify_llm_exception(_err("model not found: gpt-99"))
        assert info.code == "model_not_found"
        assert info.fatal is True

    def test_unknown_model(self):
        info = classify_llm_exception(_err("Unknown model 'foo-bar'"))
        assert info.code == "model_not_found"

    # ---- context too long ----
    def test_context_length_exceeded(self):
        info = classify_llm_exception(_err("context_length_exceeded"))
        assert info.code == "context_too_long"
        assert info.fatal is True

    def test_too_many_tokens(self):
        info = classify_llm_exception(_err("Too many tokens in request"))
        assert info.code == "context_too_long"

    def test_maximum_context(self):
        info = classify_llm_exception(_err("Maximum context length reached"))
        assert info.code == "context_too_long"

    # ---- 429 / rate limit ----
    def test_429_is_rate_limited(self):
        info = classify_llm_exception(_err("429 Too Many Requests"))
        assert info.code == "rate_limited"
        assert info.retryable is True
        assert info.fatal is False

    def test_rate_limit_keyword(self):
        info = classify_llm_exception(_err("rate limit exceeded"))
        assert info.code == "rate_limited"

    # ---- timeout ----
    def test_timeout_keyword(self):
        info = classify_llm_exception(_err("Request timeout"))
        assert info.code == "timeout"
        assert info.retryable is True

    def test_timed_out(self):
        info = classify_llm_exception(_err("The request timed out"))
        assert info.code == "timeout"

    # ---- 502/503/504 provider unavailable ----
    def test_502_bad_gateway(self):
        info = classify_llm_exception(_err("502 Bad Gateway"))
        assert info.code == "provider_unavailable"
        assert info.retryable is True

    def test_503_service_unavailable(self):
        info = classify_llm_exception(_err("503 Service Unavailable"))
        assert info.code == "provider_unavailable"

    def test_504_gateway_timeout(self):
        info = classify_llm_exception(_err("504 Gateway Timeout"))
        # 504 本质是上游超时，分类为 timeout（HTTP 语义上 504 = Gateway Timeout）
        assert info.code == "timeout"
        assert info.retryable is True

    def test_bad_gateway_keyword(self):
        info = classify_llm_exception(_err("upstream bad gateway"))
        assert info.code == "provider_unavailable"

    # ---- connection ----
    def test_connection_error(self):
        info = classify_llm_exception(_err("Connection refused"))
        assert info.code == "connection_error"
        assert info.retryable is True

    def test_network_error(self):
        info = classify_llm_exception(_err("Network unreachable"))
        assert info.code == "connection_error"

    # ---- JSON error ----
    def test_json_decode_error(self):
        info = classify_llm_exception(_err("json decode error"))
        assert info.code == "json_error"
        # json_error 是非 fatal 但也不重试（schema 错改不动）
        assert info.fatal is False

    def test_json_parse_error(self):
        info = classify_llm_exception(_err("Expecting value: line 1 column 1 (json parse)"))
        assert info.code == "json_error"

    # ---- unknown ----
    def test_unknown_message_is_retryable(self):
        info = classify_llm_exception(_err("Something completely unexpected"))
        assert info.code == "unknown"
        assert info.retryable is True
        assert info.fatal is False

    def test_empty_message_is_unknown(self):
        info = classify_llm_exception(_err(""))
        assert info.code == "unknown"
        # user_message 应该有兜底值
        assert info.user_message

    # ---- 优先级 ----
    def test_401_takes_precedence_over_rate_limit_text(self):
        # 如果同时含 401 和 rate-limit 子串，401 优先（auth 先匹配）
        info = classify_llm_exception(_err("401 unauthorized, but also rate limit"))
        assert info.code == "auth_error"

    def test_user_message_is_chinese_or_meaningful(self):
        # 所有非 unknown 应有中文 user_message
        for msg in [
            "401 Unauthorized",
            "403 Forbidden",
            "model not found",
            "context_length_exceeded",
            "429",
            "timeout",
            "503",
            "Connection refused",
            "json decode error",
        ]:
            info = classify_llm_exception(_err(msg))
            assert info.user_message, f"empty user_message for {msg!r}"
            # 至少 5 个字符
            assert len(info.user_message) >= 5, f"too short user_message for {msg!r}"
