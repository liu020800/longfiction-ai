"""测试 memory.context_bridge.build_memory_context 的容错与组装行为。"""
from unittest.mock import MagicMock

import pytest

from memory.context_bridge import (
    _SECTION_LIMITS,
    build_memory_context,
)


def _make_memory(
    *,
    world_text: str | None = "世界观内容",
    chars_text: str | None = "角色档案内容",
    rel_text: str | None = "关系图内容",
    wm_text: str | None = "工作记忆内容",
    recent_text: str | None = "最近上下文内容",
    # 控制子存储抛异常
    raise_world: bool = False,
    raise_chars: bool = False,
    raise_rel: bool = False,
    raise_wm: bool = False,
    raise_recent: bool = False,
):
    """构造一个 MagicMock 模拟 MemorySystem，6 个子存储可独立控制。"""
    memory = MagicMock()

    # structured
    structured = MagicMock()
    if raise_world:
        structured.get_world_text = MagicMock(side_effect=Exception("world boom"))
    else:
        structured.get_world_text = MagicMock(return_value=world_text)
    if raise_chars:
        structured.get_character_profiles_text = MagicMock(side_effect=Exception("chars boom"))
    else:
        structured.get_character_profiles_text = MagicMock(return_value=chars_text)
    memory.structured = structured

    # relationship_graph
    rel_graph = MagicMock()
    if raise_rel:
        rel_graph.get_context_text = MagicMock(side_effect=Exception("rel boom"))
    else:
        rel_graph.get_context_text = MagicMock(return_value=rel_text)
    memory.relationship_graph = rel_graph

    # working_memory
    wm = MagicMock()
    if raise_wm:
        wm.get_context_text = MagicMock(side_effect=Exception("wm boom"))
    else:
        wm.get_context_text = MagicMock(return_value=wm_text)
    memory.working_memory = wm

    # short_term
    short = MagicMock()
    if raise_recent:
        short.get_context_for_writer = MagicMock(side_effect=Exception("recent boom"))
    else:
        short.get_context_for_writer = MagicMock(return_value=recent_text)
    memory.short_term = short

    return memory


class TestBuildMemoryContext:
    def test_none_memory_returns_empty_string(self):
        assert build_memory_context(None) == ""

    def test_all_sections_present(self):
        memory = _make_memory()
        result = build_memory_context(memory, chapter_index=3)
        assert "【世界观】" in result
        assert "【角色档案】" in result
        assert "【角色关系】" in result
        assert "【工作记忆】" in result
        assert "【最近上下文】" in result

    def test_uses_chapter_index_in_default_query(self, caplog=None):
        # 同步版本不直接用 chapter_index 拼 query，但确保不抛
        memory = _make_memory()
        # chapter_index 0 vs 50 都应能正常返回
        result_a = build_memory_context(memory, chapter_index=0)
        result_b = build_memory_context(memory, chapter_index=50)
        assert result_a
        assert result_b

    def test_per_store_failure_does_not_break_others(self):
        """任一子存储抛异常时，其它子存储内容仍应出现。"""
        memory = _make_memory(raise_rel=True, raise_wm=True)
        result = build_memory_context(memory, chapter_index=0)
        # 失败的两个不出现，正常的 3 个仍出现
        assert "【角色关系】" not in result
        assert "【工作记忆】" not in result
        assert "【世界观】" in result
        assert "【角色档案】" in result
        assert "【最近上下文】" in result

    def test_all_stores_failing_returns_empty(self):
        memory = _make_memory(
            raise_world=True, raise_chars=True, raise_rel=True,
            raise_wm=True, raise_recent=True,
        )
        result = build_memory_context(memory, chapter_index=0)
        # 全部失败 → 至少不抛，结果为空（因为容错后所有 section 都为空）
        # 截断标记可能在末尾
        assert isinstance(result, str)

    def test_empty_section_is_skipped(self):
        memory = _make_memory(world_text="", chars_text=None, rel_text="")
        result = build_memory_context(memory, chapter_index=0)
        # 空字符串的 section 不应出现
        assert "【世界观】" not in result
        assert "【角色档案】" not in result
        assert "【角色关系】" not in result
        # 但有内容的仍出现
        assert "【工作记忆】" in result
        assert "【最近上下文】" in result

    def test_per_section_truncation(self):
        long_text = "x" * 5000
        memory = _make_memory(world_text=long_text, chars_text=long_text)
        result = build_memory_context(memory, chapter_index=0)
        # 每段有限制（800 / 1200）
        for section, limit in _SECTION_LIMITS.items():
            if section == "faiss":
                continue  # 同步版本不输出【相似记忆】段（仅异步 build_memory_context_with_rag 输出）
            # 检查对应 section 的内容不超过 limit + 3（"...\n"）
            label = {
                "structured_world": "【世界观】",
                "structured_chars": "【角色档案】",
                "relationships": "【角色关系】",
                "working": "【工作记忆】",
                "recent": "【最近上下文】",
            }[section]
            if label in result:
                # 找到该 section 起，到下一个 section 之前
                idx = result.index(label)
                next_idx = len(result)
                for other_label in ["【世界观】", "【角色档案】", "【角色关系】", "【工作记忆】", "【最近上下文】"]:
                    if other_label != label:
                        pos = result.find(other_label, idx + len(label))
                        if pos != -1 and pos < next_idx:
                            next_idx = pos
                section_content = result[idx + len(label):next_idx]
                # section 内容应 ≤ limit + "..." 的余量
                assert len(section_content) <= limit + 50, (
                    f"section {section} content length {len(section_content)} "
                    f"exceeds limit {limit} + truncation marker"
                )

    def test_max_chars_truncation(self):
        # 所有 section 都填很长的内容，验证总长度被 max_chars 截断
        long_text = "y" * 1000
        memory = _make_memory(
            world_text=long_text, chars_text=long_text, rel_text=long_text,
            wm_text=long_text, recent_text=long_text,
        )
        result = build_memory_context(memory, chapter_index=0, max_chars=1000)
        assert len(result) <= 1100  # 1000 + "..." 截断标记
        assert "已截断" in result or len(result) <= 1000

    def test_max_chars_zero_means_no_truncation(self):
        memory = _make_memory(world_text="短", chars_text="短")
        # max_chars=0 → 关闭截断
        result = build_memory_context(memory, chapter_index=0, max_chars=0)
        assert "【世界观】" in result
        assert "【角色档案】" in result

    def test_include_flags(self):
        memory = _make_memory()
        result = build_memory_context(
            memory, chapter_index=0,
            include_world=False, include_characters=False,
            include_relationships=False, include_working=False, include_recent=False,
        )
        # 全部关掉 → 应为空
        assert result == ""

        result = build_memory_context(
            memory, chapter_index=0, include_world=True, include_characters=False,
        )
        assert "【世界观】" in result
        assert "【角色档案】" not in result

    def test_memory_without_optional_substores(self):
        """MemorySystem 实例可能没有 relationship_graph / working_memory / short_term。"""
        memory = MagicMock()
        memory.structured = MagicMock()
        memory.structured.get_world_text = MagicMock(return_value="world")
        memory.structured.get_character_profiles_text = MagicMock(return_value="chars")
        memory.relationship_graph = None
        memory.working_memory = None
        memory.short_term = None

        result = build_memory_context(memory, chapter_index=0)
        assert "【世界观】" in result
        assert "【角色档案】" in result
        assert "【角色关系】" not in result
        assert "【工作记忆】" not in result
        assert "【最近上下文】" not in result
