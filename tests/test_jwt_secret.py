"""测试 core.config.get_jwt_secret 的优先级与边界条件。"""
import pytest

from core.config import Settings


class TestGetJwtSecret:
    def test_explicit_jwt_secret_returned_when_set(self, monkeypatch):
        """JWT_SECRET_KEY 设置且长度 ≥ 32 时优先返回。"""
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 32)
        s = Settings(DEBUG=False)
        assert s.get_jwt_secret() == "a" * 32

    def test_short_jwt_secret_falls_through_in_debug(self, monkeypatch):
        """DEBUG 模式下即使 JWT_SECRET_KEY 短，也使用 dev secret。"""
        monkeypatch.setenv("JWT_SECRET_KEY", "short")
        s = Settings(DEBUG=True)
        # 短 secret 不满足 ≥ 32 位 → 走 dev fallback
        assert s.get_jwt_secret() == "dev-longfiction-jwt-secret-change-me-please-32chars"

    def test_debug_uses_dev_secret_when_unset(self, monkeypatch):
        """DEBUG 模式未配置 JWT_SECRET_KEY 时使用固定 dev secret。"""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        s = Settings(DEBUG=True, JWT_SECRET_KEY="")
        assert s.get_jwt_secret() == "dev-longfiction-jwt-secret-change-me-please-32chars"

    def test_production_without_secret_raises(self, monkeypatch):
        """生产环境（DEBUG=False）且未配置 JWT_SECRET_KEY 必须抛 ValueError。"""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        s = Settings(DEBUG=False, JWT_SECRET_KEY="")
        with pytest.raises(ValueError) as exc_info:
            s.get_jwt_secret()
        assert "JWT_SECRET_KEY" in str(exc_info.value)

    def test_production_with_too_short_secret_raises(self, monkeypatch):
        """生产环境 JWT_SECRET_KEY 长度 < 32 必须抛 ValueError。"""
        monkeypatch.setenv("JWT_SECRET_KEY", "x" * 16)
        s = Settings(DEBUG=False)
        with pytest.raises(ValueError):
            s.get_jwt_secret()

    def test_does_not_depend_on_llm_api_key(self, monkeypatch):
        """核心不变性：换 LLM API Key 不应影响 JWT 密钥。"""
        monkeypatch.setenv("JWT_SECRET_KEY", "b" * 32)
        monkeypatch.setenv("LLM_API_KEY", "sk-old-key-aaaaaaaaaaaaaaaa")
        s1 = Settings(DEBUG=False)
        secret_before = s1.get_jwt_secret()

        # 模拟"换 LLM Key"
        monkeypatch.setenv("LLM_API_KEY", "sk-new-key-bbbbbbbbbbbbbbbb")
        s2 = Settings(DEBUG=False)
        secret_after = s2.get_jwt_secret()

        # 换 LLM Key 后 JWT 密钥必须保持不变
        assert secret_before == secret_after
        assert secret_after == "b" * 32
