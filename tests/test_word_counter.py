import pytest
import asyncio
from core.word_counter import (
    count_chinese_words,
    intelligent_trim,
    intelligent_expand,
    compute_style_drift,
    get_best_version_with_style_drift,
    CorrectionHistory,
    CorrectionSnapshot,
    CorrectionStrategy,
    compute_deviation,
    _compute_compress_priority,
    _identify_protected_nodes,
)


def test_count_chinese_words():
    assert count_chinese_words("你好世界") == 4
    assert count_chinese_words("") == 0
    assert count_chinese_words("Hello") == 2
    assert count_chinese_words("你好Hello世界") == 6


def test_identify_protected_nodes():
    text = "他们发生了冲突。风景很美丽。真相大白。然后离开了。"
    nodes = _identify_protected_nodes(text)
    assert len(nodes) >= 2
    node_texts = [text[s:e] for s, e in nodes]
    assert any("冲突" in t for t in node_texts)
    assert any("真相" in t for t in node_texts)


def test_compute_compress_priority():
    env_para = "远处的山峦在夕阳下显得格外壮阔，风景如画，美不胜收。"
    assert _compute_compress_priority(env_para) > 0.2

    conflict_para = "两人爆发了激烈的冲突，剑拔弩张，大战一触即发。"
    assert _compute_compress_priority(conflict_para) < 0.2

    transition_para = "于是他转身离开了。随后天色渐暗。"
    assert _compute_compress_priority(transition_para) > 0.2


@pytest.mark.asyncio
async def test_intelligent_trim_basic():
    env_paras = "远处的山峦在夕阳下显得格外壮阔，风景如画，美不胜收。\n\n" * 20
    conflict_para = "两人爆发了激烈的冲突，剑拔弩张，大战一触即发。真相即将大白。\n\n"
    transition_paras = "于是他转身离开了。随后天色渐暗。\n\n" * 10
    long_text = env_paras + conflict_para + transition_paras
    target = 100
    result = await intelligent_trim(long_text, target)
    assert count_chinese_words(result) <= target * 1.2


@pytest.mark.asyncio
async def test_intelligent_trim_no_change_when_within_tolerance():
    text = "这是一段测试文本。" * 10
    target = count_chinese_words(text)
    result = await intelligent_trim(text, target)
    assert result == text


@pytest.mark.asyncio
async def test_intelligent_expand_returns_original_when_no_llm():
    text = "短文本。"
    result = await intelligent_expand(text, 500, llm_call=None)
    assert result == text


def test_get_best_version_with_style_drift():
    history = CorrectionHistory()
    history.save(CorrectionSnapshot(
        text="版本A", word_count=1900, quality_score=0.8,
        strategy=CorrectionStrategy.TRIM, style_drift=0.1
    ))
    history.save(CorrectionSnapshot(
        text="版本B", word_count=1800, quality_score=0.7,
        strategy=CorrectionStrategy.TRIM, style_drift=0.5
    ))
    best_text, best_dev = get_best_version_with_style_drift(history, 2000, style_drift_threshold=0.3)
    assert best_text == "版本A"
