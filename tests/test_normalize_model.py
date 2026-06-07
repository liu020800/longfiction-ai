"""测试 core.model_router._normalize_for_litellm 对不同 LLM_PROVIDER 的行为。"""
import pytest

from core import model_router
from core.config import Settings


def _with_provider(provider: str) -> Settings:
    """构造一个临时 Settings 实例覆盖 LLM_PROVIDER。"""
    return Settings(LLM_PROVIDER=provider)


class TestNormalizeForLiteLLM:
    def test_empty_string_passes_through(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("openai_compatible"))
        assert model_router._normalize_for_litellm("") == ""

    def test_already_prefixed_passes_through(self, monkeypatch):
        # 已有 provider 前缀的不修改
        monkeypatch.setattr(model_router, "settings", _with_provider("openai_compatible"))
        assert model_router._normalize_for_litellm("openai/gpt-4o-mini") == "openai/gpt-4o-mini"
        assert model_router._normalize_for_litellm("deepseek/deepseek-chat") == "deepseek/deepseek-chat"
        assert model_router._normalize_for_litellm("dashscope/qwen-plus") == "dashscope/qwen-plus"

    def test_openai_provider_no_prefix(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("openai"))
        assert model_router._normalize_for_litellm("gpt-4o-mini") == "gpt-4o-mini"
        assert model_router._normalize_for_litellm("gpt-4-turbo") == "gpt-4-turbo"

    def test_openai_compatible_provider_adds_openai_prefix(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("openai_compatible"))
        assert model_router._normalize_for_litellm("gpt-4o-mini") == "openai/gpt-4o-mini"

    @pytest.mark.parametrize("alias", ["newapi", "oneapi", "lmstudio"])
    def test_openai_compatible_aliases_all_add_prefix(self, monkeypatch, alias):
        monkeypatch.setattr(model_router, "settings", _with_provider(alias))
        assert model_router._normalize_for_litellm("qwen2.5-7b") == "openai/qwen2.5-7b"

    def test_deepseek_provider_adds_deepseek_prefix(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("deepseek"))
        assert model_router._normalize_for_litellm("deepseek-chat") == "deepseek/deepseek-chat"
        # 已有前缀不重复加
        assert model_router._normalize_for_litellm("deepseek/deepseek-coder") == "deepseek/deepseek-coder"

    def test_qwen_provider_adds_dashscope_prefix(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("qwen"))
        assert model_router._normalize_for_litellm("qwen-plus") == "dashscope/qwen-plus"
        # 已有前缀不重复加
        assert model_router._normalize_for_litellm("dashscope/qwen-max") == "dashscope/qwen-max"

    def test_ollama_provider_adds_ollama_prefix(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("ollama"))
        assert model_router._normalize_for_litellm("llama3.1") == "ollama/llama3.1"
        # 已有前缀不重复加
        assert model_router._normalize_for_litellm("ollama/mistral") == "ollama/mistral"

    def test_unknown_provider_passes_through(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("some_future_provider"))
        assert model_router._normalize_for_litellm("mystery-model") == "mystery-model"

    def test_provider_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(model_router, "settings", _with_provider("OPENAI_COMPATIBLE"))
        assert model_router._normalize_for_litellm("gpt-4o-mini") == "openai/gpt-4o-mini"
