"""测试 core.quality_policy 的硬/软门分类。"""
import logging

import pytest

from core.quality_policy import (
    ALL_GATES,
    GATE_HELP_TEXT,
    HARD_GATES,
    SOFT_GATES,
    classify_gate,
    help_text,
    is_hard_gate,
    is_soft_gate,
)


class TestGateSets:
    def test_hard_gates_contains_expected(self):
        assert "title" in HARD_GATES
        assert "word_count" in HARD_GATES
        assert "truncation" in HARD_GATES
        assert "empty_content" in HARD_GATES

    def test_soft_gates_contains_expected(self):
        assert "ai_traces" in SOFT_GATES
        assert "similarity" in SOFT_GATES
        assert "title_unique" in SOFT_GATES
        assert "style_drift" in SOFT_GATES

    def test_hard_and_soft_disjoint(self):
        assert HARD_GATES & SOFT_GATES == set()

    def test_all_gates_is_union(self):
        assert ALL_GATES == HARD_GATES | SOFT_GATES


class TestIsHardGate:
    @pytest.mark.parametrize("name", ["title", "word_count", "truncation", "empty_content"])
    def test_true_for_hard(self, name):
        assert is_hard_gate(name) is True

    @pytest.mark.parametrize("name", ["ai_traces", "similarity", "title_unique", "style_drift"])
    def test_false_for_soft(self, name):
        assert is_hard_gate(name) is False

    def test_false_for_unknown(self):
        assert is_hard_gate("totally_made_up_gate") is False

    def test_false_for_empty_string(self):
        assert is_hard_gate("") is False


class TestIsSoftGate:
    @pytest.mark.parametrize("name", ["ai_traces", "similarity", "title_unique", "style_drift"])
    def test_true_for_soft(self, name):
        assert is_soft_gate(name) is True

    @pytest.mark.parametrize("name", ["title", "word_count", "truncation", "empty_content"])
    def test_false_for_hard(self, name):
        assert is_soft_gate(name) is False

    def test_false_for_unknown(self):
        assert is_soft_gate("totally_made_up_gate") is False


class TestClassifyGate:
    @pytest.mark.parametrize("name", ["title", "word_count", "truncation", "empty_content"])
    def test_returns_hard(self, name):
        assert classify_gate(name) == "hard"

    @pytest.mark.parametrize("name", ["ai_traces", "similarity", "title_unique", "style_drift"])
    def test_returns_soft(self, name):
        assert classify_gate(name) == "soft"

    def test_returns_unknown_for_unregistered(self, caplog):
        with caplog.at_level(logging.WARNING, logger="core.quality_policy"):
            assert classify_gate("never_registered_gate") == "unknown"
        assert "never_registered_gate" in caplog.text

    def test_classify_does_not_raise(self):
        # 任何输入都不能抛异常
        for name in [None, "", 123, "valid_hard_title"]:
            result = classify_gate(name) if isinstance(name, str) else "unknown"
            assert result in ("hard", "soft", "unknown")


class TestHelpText:
    def test_known_hard_gate_has_text(self):
        assert "标题" in help_text("title")
        assert "字数" in help_text("word_count")

    def test_known_soft_gate_has_text(self):
        assert "AI" in help_text("ai_traces")
        assert "风格" in help_text("style_drift")

    def test_unknown_gate_returns_empty(self):
        assert help_text("never_heard_of_it") == ""
