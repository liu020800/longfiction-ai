"""程序级质量门单元测试。

覆盖 P0/P1 修复的关键检查函数，确保：
- 脏词标题被正确拦截
- 截断检测在末尾无标点/为 CJK 字符时触发
- 跨章相似度在 Jaccard > 0.5 时触发
- OutputValidator 在多种违规并存时合并为单次异常
- TitleSanitizer 能从脏词中恢复出可用标题

不依赖网络/LLM/数据库，全部纯函数。
"""
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `core.*` imports work when running directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from core.validators import OutputValidator, OutputValidationError, TitleSanitizer


# ----------------------------------------------------------------------
# 1-2: 脏词标题检测（PlannerAgent._is_dirty_title 的封装）
# ----------------------------------------------------------------------

def test_is_dirty_title_clean_passes():
    """有意义的标题不应被识别为脏词。"""
    from agents.planner_agent import PlannerAgent
    p = PlannerAgent()
    assert p._is_dirty_title("黑潮初现") is False
    assert p._is_dirty_title("地下之城") is False
    # "重逢" 是 2 字，_is_dirty_title 把 ≤2 字视为脏词（保守策略）
    # 所以用一个 3 字的正常标题
    assert p._is_dirty_title("久别重逢") is False


def test_is_dirty_title_dirty_blocked():
    """所有脏词模式应被识别。"""
    from agents.planner_agent import PlannerAgent
    p = PlannerAgent()
    for dirty in ["主角", "中段", "大结局", "最终对决", "敌方", "本章", "阶段"]:
        assert p._is_dirty_title(dirty) is True, f"应识别为脏词: {dirty}"


# ----------------------------------------------------------------------
# 3-4: 截断检测（WriterAgent._is_truncated_ending 的封装）
# ----------------------------------------------------------------------

def test_is_truncated_ending_detected():
    """末尾为顿号、CJK 字符（无标点）应被识别为截断。"""
    from agents.writer_agent import WriterAgent
    # 末尾是顿号
    assert WriterAgent._is_truncated_ending("他说：") is True
    # 末尾是 CJK 字符无标点
    assert WriterAgent._is_truncated_ending("他走") is True
    # 空文本（边界）
    assert WriterAgent._is_truncated_ending("") is False
    # 末尾是 MID_SENTENCE 字符
    assert WriterAgent._is_truncated_ending("他走了着") is True


def test_is_truncated_ending_normal_passes():
    """末尾为句号/感叹号/问号应通过。"""
    from agents.writer_agent import WriterAgent
    assert WriterAgent._is_truncated_ending("他说：你好。") is False
    assert WriterAgent._is_truncated_ending("太好了！") is False
    assert WriterAgent._is_truncated_ending("这是为什么？") is False
    # 引号结尾
    assert WriterAgent._is_truncated_ending("他说完便离开了。\"") is False


# ----------------------------------------------------------------------
# 5-6: 跨章相似度（WriterAgent._is_too_similar 的封装）
# ----------------------------------------------------------------------

def test_is_too_similar_detected():
    """两段重复内容应被检测为过相似。"""
    from agents.writer_agent import WriterAgent
    agent = WriterAgent.__new__(WriterAgent)
    # 两段几乎完全相同
    same_para = "林逸的手指在键盘上顿住，屏幕上的数据开始剧烈波动，地下室的灯光闪烁了几下，然后彻底熄灭。"
    assert agent._is_too_similar(same_para, same_para) is True
    # 略有变化但大部分 4-gram 重叠
    para_a = "林逸的手指在键盘上顿住，屏幕上的数据开始剧烈波动，地下室的灯光闪烁了几下。"
    para_b = "林逸的手指在键盘上顿住，屏幕上的数据开始剧烈波动，地下室的灯光闪烁了几下，然后熄灭。"
    assert agent._is_too_similar(para_a, para_b) is True


def test_is_too_similar_distinct_passes():
    """两段不相关内容不应被检测为过相似。"""
    from agents.writer_agent import WriterAgent
    agent = WriterAgent.__new__(WriterAgent)
    para_a = "林逸走在雨后的街道上，看着远处闪烁的霓虹灯，心里想着今天发生的事。"
    para_b = "陈浩在实验室里盯着显微镜下的细胞样本，记录下新的发现，准备明天开会讨论。"
    assert agent._is_too_similar(para_a, para_b) is False


# ----------------------------------------------------------------------
# 7-10: OutputValidator 聚合检查
# ----------------------------------------------------------------------

def _make_clean_text(approx_chars: int) -> str:
    """生成一段约 N 字、结尾标点正常、无 AI 痕迹、无脏词的纯中文文本。"""
    base = (
        "林逸站在地下室的入口处，手里握着那把已经用了三年的钥匙。"
        "他深吸一口气，推开铁门，潮湿的空气迎面扑来，带着一股陈旧金属的味道。"
        "走廊的尽头，一盏白炽灯在闪烁，映照出墙上斑驳的油漆痕迹。"
        "他沿着走廊向里走去，脚步声在空旷的地下室里回荡，像是某种古老的回声。"
    )
    text = ""
    while len(text) < approx_chars:
        text += base
    return text[:approx_chars] + "。"


def test_output_validator_passes_clean_chapter():
    """干净标题 + 足量字数 + 正常结尾 + 低 AI 密度 → 不抛错。"""
    validator = OutputValidator(
        # 用空短语列表 + 低密度限制，确保测试文本不会被误判
        ai_trace_phrases=["——不是", "心中涌起", "指节发白"],
        ai_trace_max=3,
        ai_trace_density_limit=10.0,  # 故意放高，让短测试文本能通过
        word_count_lower_pct=0.85,
        word_count_lower_pct_last=0.95,
        word_count_absolute_min=200,
    )
    clean_text = _make_clean_text(2200)  # 约 2200 字
    # 不应抛错
    validator.validate_all(
        title="黑潮初现",
        content=clean_text,
        target_words=2000,
        is_last_chapter=False,
        previous_ending="",
    )


def test_output_validator_raises_on_dirty_title():
    """脏标题 → OutputValidationError，category='title'。"""
    validator = OutputValidator(
        ai_trace_phrases=[],
        ai_trace_max=3,
    )
    with pytest.raises(OutputValidationError) as exc_info:
        validator.validate_all(
            title="主角离开",
            content=_make_clean_text(2200),
            target_words=2000,
            is_last_chapter=False,
        )
    assert exc_info.value.category == "title"
    assert any("标题" in v for v in exc_info.value.violations)


def test_output_validator_raises_on_low_word_count():
    """末章字数 80% target → OutputValidationError，category='word_count'。"""
    validator = OutputValidator(
        ai_trace_phrases=[],
        ai_trace_max=3,
        word_count_lower_pct=0.85,
        word_count_lower_pct_last=0.95,  # 末章要求 95%
        word_count_absolute_min=200,
    )
    short_text = _make_clean_text(1600)  # 80% of 2000
    with pytest.raises(OutputValidationError) as exc_info:
        validator.validate_all(
            title="最终之战",  # 用干净标题让字数检查先触发
            content=short_text,
            target_words=2000,
            is_last_chapter=True,
        )
    assert exc_info.value.category == "word_count"
    assert any("末章字数" in v for v in exc_info.value.violations)


def test_output_validator_collects_all_violations():
    """脏标题 + 字数不足 + 截断 → 单次异常，violations 列表 ≥ 3 项。"""
    validator = OutputValidator(
        ai_trace_phrases=["——不是", "瞳孔骤缩"],
        ai_trace_max=3,
        word_count_lower_pct=0.85,
        word_count_lower_pct_last=0.95,
        word_count_absolute_min=200,
    )
    bad_text = "主角" + "林逸走在路上，"  # 短、脏标题、截断、无结尾标点
    with pytest.raises(OutputValidationError) as exc_info:
        validator.validate_all(
            title="主角离开",
            content=bad_text,
            target_words=2000,
            is_last_chapter=False,
        )
    assert len(exc_info.value.violations) >= 3, (
        f"应聚合多种违规，实际只有 {len(exc_info.value.violations)} 条: {exc_info.value.violations}"
    )


# ----------------------------------------------------------------------
# 额外测试：TitleSanitizer
# ----------------------------------------------------------------------

def test_title_sanitizer_cleans_dirty_prefix():
    """剥除前缀脏词。"""
    sanitizer = TitleSanitizer()
    # "主角" 脏词在前面，应被剥除
    assert sanitizer.clean("主角安全区", chapter_index=12) == "安全区"
    # "中段" 脏词在前面
    assert sanitizer.clean("中段转折", chapter_index=27) == "转折"
    # "最终对决" 脏词在前面
    assert sanitizer.clean("最终对决之时", chapter_index=49) == "之时"
    # 多轮剥除：剥到所有脏词都清除（"中段"和"阶段"都是脏词）→ 兜底
    result = sanitizer.clean("中段阶段", chapter_index=20)
    # "中段"剥除 → "阶段"；"阶段"剥除 → "" → 触发第N节兜底
    assert result == "第21节", f"Expected fallback to '第21节', got '{result}'"


def test_title_sanitizer_fallback():
    """完全剥除后用第N节兜底。"""
    sanitizer = TitleSanitizer()
    assert sanitizer.clean("主角", chapter_index=15) == "第16节"
    assert sanitizer.clean("中段", chapter_index=27) == "第28节"
    # 无 chapter_index 时的兜底
    assert sanitizer.clean("") == "未命名章节"


# ----------------------------------------------------------------------
# 跨章标题唯一性测试（22754859 项目问题）
# ----------------------------------------------------------------------

def test_validate_title_uniqueness_detects_duplicate():
    """精确重复：与历史某章标题完全相同 → violation。"""
    validator = OutputValidator(ai_trace_phrases=[])
    prev = ["第1章 重生在黄河边", "第2章 捡来的第一笔钱", "第3章 林晓的眼泪"]
    violations = validator.validate_title_uniqueness("第3章 林晓的眼泪", prev)
    assert len(violations) == 1
    assert "重复" in violations[0]


def test_validate_title_uniqueness_detects_similar_prefix():
    """前缀坍缩：与近章前 3 字相同 → violation（捕捉"扩大组织、"等 stage 桶坍缩）。"""
    validator = OutputValidator(ai_trace_phrases=[])
    # 22754859 的真实模式：连续 3+ 章共用"扩大组织"前缀
    prev = [
        "第13章 扩大组织·初现",
        "第14章 扩大组织·暗涌",
    ]
    violations = validator.validate_title_uniqueness("第15章 扩大组织·试探", prev)
    assert len(violations) == 1
    assert "相似" in violations[0] or "坍缩" in violations[0]


def test_validate_title_uniqueness_passes_distinct():
    """完全不同标题 → 空列表。"""
    validator = OutputValidator(ai_trace_phrases=[])
    prev = ["第1章 重生在黄河边", "第2章 捡来的第一笔钱", "第3章 林晓的眼泪"]
    violations = validator.validate_title_uniqueness("第4章 股市的紫色光芒", prev)
    assert violations == []


def test_validate_title_uniqueness_ignores_short_titles():
    """短标题 (<3 字) 不强制唯一，避免误伤合理短标题。"""
    validator = OutputValidator(ai_trace_phrases=[])
    prev = ["第1章 黎明", "第2章 黄昏", "第3章 星辰"]
    # 当前标题只有 2 字，prev 有 "黎明"/"黄昏"，但因为 < 3 字应放行
    violations = validator.validate_title_uniqueness("第4章 夜归", prev)
    assert violations == []


def test_validate_all_with_previous_titles_raises_on_duplicate():
    """validate_all 接入 previous_titles 后应触发 title_unique 类别。"""
    from core.validators import OutputValidationError
    validator = OutputValidator(
        ai_trace_phrases=[],
        word_count_absolute_min=200,
        word_count_lower_pct=0.85,
        word_count_lower_pct_last=0.95,
        ai_trace_density_limit=10.0,  # 宽松，避免被 AI 痕迹干扰
    )
    prev_titles = ["第13章 扩大组织·初现", "第14章 扩大组织·暗涌"]
    # 制造一个干净但标题重复的章节
    content = "这是一些填充文本。" * 60
    with pytest.raises(OutputValidationError) as exc_info:
        validator.validate_all(
            title="第15章 扩大组织·试探",
            content=content,
            target_words=2000,
            is_last_chapter=False,
            previous_ending="",
            previous_titles=prev_titles,
        )
    assert exc_info.value.category == "title_unique"
    assert any("坍缩" in v or "相似" in v for v in exc_info.value.violations)


def test_make_progressive_chapter_unique_titles():
    """5 个连续章节（同一 stage 桶）应产出 5 个不同标题（Fix B 验证）。

    模拟 50 章书的第 13-17 章（应落入同一 stage 桶）。
    """
    from agents.planner_agent import PlannerAgent
    from core.models import ChapterOutline
    planner = PlannerAgent.__new__(PlannerAgent)  # 跳过 __init__，只测纯函数
    existing: list[ChapterOutline] = []
    titles: list[str] = []
    for i in range(12, 17):  # 5 个连续章节
        ch = planner._make_progressive_chapter(
            outline="测试 outline",
            existing=existing,
            chapter_index=i,
            total_chapters=50,
        )
        titles.append(ch.title)
        existing.append(ch)
    # 5 章必须全部不同（Fix B 关键断言）
    assert len(set(titles)) == 5, f"Titles should be unique, got: {titles}"
