"""测试 agents.style_controller 和 style_migrator 模块。"""
import pytest

from agents.style_controller import (
    StyleFeatures,
    StyleProfile,
    extract_style_features,
    get_style_profile,
    learn_style_from_samples,
    style_features_to_prompt,
    style_distance,
    PRESET_STYLES,
)
from agents.enhancement.sentence_diversifier import (
    SentenceDiversifier,
    diversify_text,
)


class TestExtractStyleFeatures:
    def test_empty(self):
        f = extract_style_features("")
        assert f.total_chars == 0

    def test_basic(self):
        text = "林远站在山巅。风吹过他的衣襟。「你是谁？」他问道。"
        f = extract_style_features(text)
        assert f.total_chars > 0
        assert f.total_sentences > 0

    def test_long_text(self):
        text = "林远站在山巅，看着远方。" * 5
        f = extract_style_features(text)
        # 文本存在即可
        assert f.total_chars > 0
        assert f.total_sentences > 0


class TestStyleProfile:
    def test_preset_web_novel(self):
        profile = get_style_profile("web_novel")
        assert profile is not None
        assert profile.name == "web_novel"

    def test_preset_unknown(self):
        assert get_style_profile("nonexistent") is None

    def test_learn_from_samples(self):
        samples = [
            "林远拔出剑，直指前方。「让开！」他大喝。",
            "敌人冷笑着。「你以为能赢我？」",
            "剑气纵横，碎石飞溅。",
        ]
        profile = learn_style_from_samples(samples, "test_style")
        assert profile.name == "test_style"
        assert profile.features.total_chars > 0


class TestStyleFeaturesToPrompt:
    def test_basic(self):
        profile = get_style_profile("web_novel")
        prompt = style_features_to_prompt(profile)
        assert "web_novel" in prompt
        assert "句子长度" in prompt


class TestStyleDistance:
    def test_identical(self):
        a = StyleFeatures(avg_sentence_length=20.0, dialogue_ratio=0.3)
        b = StyleFeatures(avg_sentence_length=20.0, dialogue_ratio=0.3)
        d = style_distance(a, b)
        assert d < 0.01  # 几乎为 0

    def test_different(self):
        a = StyleFeatures(avg_sentence_length=10.0)
        b = StyleFeatures(avg_sentence_length=50.0)
        d = style_distance(a, b)
        assert d > 0.1


class TestSentenceDiversifier:
    def test_empty(self):
        d = SentenceDiversifier()
        result = d.diversify("")
        assert result.diversified == ""

    def test_short_text(self):
        d = SentenceDiversifier()
        text = "林远站着。"
        result = d.diversify(text)
        assert result.diversified  # 应该有输出

    def test_long_text(self):
        d = SentenceDiversifier()
        text = "林远在山巅站了很久，看着远方的云海。" * 5
        result = d.diversify(text)
        # 变换可能应用了
        assert isinstance(result.diversified, str)
        assert len(result.diversified) > 0


class TestDiversifyTextFunction:
    def test_function(self):
        result = diversify_text("测试文本。第一句。第二句。")
        assert isinstance(result, str)
