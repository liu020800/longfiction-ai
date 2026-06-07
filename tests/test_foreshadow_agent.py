"""测试 agents.foreshadow_agent.extract_foreshadows 的容错能力。

不需要真实 LLM；用 unittest.mock.patch 替换 call_llm。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.foreshadow_agent import extract_and_persist, extract_foreshadows


def _patched_call_llm(return_value):
    """构造一个 patch 上下文，call_llm 返回指定值。"""
    return patch(
        "agents.foreshadow_agent.call_llm",
        new=AsyncMock(return_value=return_value),
    )


class TestExtractForeshadows:
    @pytest.mark.asyncio
    async def test_empty_chapter_text_returns_empty(self):
        result = await extract_foreshadows(chapter_text="", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only_chapter_text_returns_empty(self):
        result = await extract_foreshadows(chapter_text="   \n\t  ", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_max_count_zero_skips_llm_call(self):
        # max_count=0 不应触发 LLM 调用
        with patch("agents.foreshadow_agent.call_llm") as mock_llm:
            result = await extract_foreshadows(
                chapter_text="有内容", chapter_index=0, max_count=0
            )
            assert result == []
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_perfect_json_normalized_correctly(self):
        llm_result = {
            "foreshadows": [
                {
                    "description": "祠堂里的古剑有异光",
                    "visible_clue": "剑身闪着幽蓝微光",
                    "hidden_truth": "这是封印魔尊的神器",
                    "importance": 4,
                    "expected_payoff_after": 10,
                    "expected_payoff_before": 50,
                    "related_characters": ["林萧", "古剑"],
                    "keywords": ["古剑", "异光", "封印"],
                }
            ]
        }
        with _patched_call_llm(llm_result):
            result = await extract_foreshadows(
                chapter_text="本章讲述了...", chapter_index=2
            )

        assert len(result) == 1
        item = result[0]
        assert item["description"] == "祠堂里的古剑有异光"
        assert item["visible_clue"] == "剑身闪着幽蓝微光"
        assert item["hidden_truth"] == "这是封印魔尊的神器"
        assert item["importance"] == 4
        assert item["expected_payoff_after"] == 10
        assert item["expected_payoff_before"] == 50
        assert item["related_characters"] == ["林萧", "古剑"]
        assert item["keywords"] == ["古剑", "异光", "封印"]
        assert item["source"] == "llm_extract"
        assert item["foreshadow_type"] == "clue"

    @pytest.mark.asyncio
    async def test_missing_fields_use_defaults(self):
        """只给 description，其它字段全缺失 → 走默认值。"""
        llm_result = {
            "foreshadows": [
                {"description": "简短伏笔"},
            ]
        }
        with _patched_call_llm(llm_result):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)

        assert len(result) == 1
        item = result[0]
        assert item["description"] == "简短伏笔"
        assert item["visible_clue"] == ""
        assert item["hidden_truth"] == ""
        assert item["importance"] == 1
        assert item["expected_payoff_after"] == 5
        assert item["expected_payoff_before"] == 30
        assert item["related_characters"] == []
        assert item["keywords"] == []

    @pytest.mark.asyncio
    async def test_wrong_field_types_fall_back_to_defaults(self):
        """字段类型错（importance 传字符串，characters 传 None）→ 容错到默认值。"""
        llm_result = {
            "foreshadows": [
                {
                    "description": "test",
                    "importance": "not_a_number",
                    "expected_payoff_after": "five",
                    "related_characters": None,
                    "keywords": "not_a_list",
                }
            ]
        }
        with _patched_call_llm(llm_result):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)

        assert len(result) == 1
        assert result[0]["importance"] == 1  # 默认
        assert result[0]["expected_payoff_after"] == 5  # 默认
        assert result[0]["related_characters"] == []  # 非 list → []
        assert result[0]["keywords"] == []  # 非 list → []

    @pytest.mark.asyncio
    async def test_top_level_non_dict_returns_empty(self):
        """LLM 返回非 dict → 返回 [] 不抛。"""
        with _patched_call_llm("not a dict"):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_foreshadows_field_not_a_list_returns_empty(self):
        """'foreshadows' 字段不是 list → 返回 [] 不抛。"""
        with _patched_call_llm({"foreshadows": "not a list"}):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_foreshadows_missing_returns_empty(self):
        """没有 'foreshadows' 字段 → 返回 []。"""
        with _patched_call_llm({"other_field": []}):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_item_without_description_is_dropped(self):
        """缺 description 的 item 被丢弃，其它正常 item 保留。"""
        llm_result = {
            "foreshadows": [
                {"visible_clue": "no description"},  # 应丢弃
                {"description": ""},  # 空字符串也应丢弃
                {"description": "valid"},
            ]
        }
        with _patched_call_llm(llm_result):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)

        assert len(result) == 1
        assert result[0]["description"] == "valid"

    @pytest.mark.asyncio
    async def test_max_count_caps_results(self):
        """max_count=2 时即使 LLM 返回 5 条也只取 2 条。"""
        llm_result = {
            "foreshadows": [
                {"description": f"item {i}"} for i in range(5)
            ]
        }
        with _patched_call_llm(llm_result):
            result = await extract_foreshadows(
                chapter_text="x", chapter_index=0, max_count=2
            )
        assert len(result) == 2
        assert result[0]["description"] == "item 0"
        assert result[1]["description"] == "item 1"

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty(self):
        """LLM 抛异常 → 返回 [] 不抛。"""
        with patch(
            "agents.foreshadow_agent.call_llm",
            new=AsyncMock(side_effect=RuntimeError("LLM down")),
        ):
            result = await extract_foreshadows(chapter_text="x", chapter_index=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_chapter_text_truncated_to_max_input(self):
        """超过 max_input_chars 的输入会被截断（仅截前段）。"""
        long_text = "a" * 10000
        llm_result = {"foreshadows": []}

        with _patched_call_llm(llm_result) as mock_llm:
            await extract_foreshadows(
                chapter_text=long_text, chapter_index=0, max_input_chars=100
            )

        # 验证传给 LLM 的 prompt 不超过 100 字正文 + 模板前缀
        assert mock_llm.call_count == 1
        call_args = mock_llm.call_args
        prompt = call_args.kwargs.get("prompt") or call_args.args[1]
        # prompt 中的章节正文部分最多 100 字
        # 总 prompt 长度应远小于 10000
        assert len(prompt) < 10000

    @pytest.mark.asyncio
    async def test_chapter_index_in_prompt(self):
        """prompt 中应包含「第 N 章」字样。"""
        with _patched_call_llm({"foreshadows": []}) as mock_llm:
            await extract_foreshadows(chapter_text="x", chapter_index=4)
        call_args = mock_llm.call_args
        prompt = call_args.kwargs.get("prompt") or call_args.args[1]
        assert "第5章" in prompt  # chapter_index=4 → 第5章（人读从 1 开始）


class TestExtractAndPersist:
    @pytest.mark.asyncio
    async def test_no_items_returns_zero(self):
        with _patched_call_llm({"foreshadows": []}):
            saved = await extract_and_persist(
                chapter_idx=0, chapter_text="x", pipeline=MagicMock()
            )
        assert saved == 0

    @pytest.mark.asyncio
    async def test_persists_each_valid_item(self):
        llm_result = {
            "foreshadows": [
                {"description": f"item {i}"} for i in range(3)
            ]
        }
        pipeline = MagicMock()
        pipeline._build_foreshadow_payload = MagicMock(
            side_effect=lambda idx, desc: {"description": desc, "status": "active"}
        )
        pipeline._persist_foreshadow_payload = MagicMock()
        pipeline.foreshadow_service = MagicMock()

        with _patched_call_llm(llm_result):
            saved = await extract_and_persist(
                chapter_idx=0, chapter_text="x", pipeline=pipeline
            )

        assert saved == 3
        assert pipeline._persist_foreshadow_payload.call_count == 3

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_stop_others(self):
        """一个 item 落库失败不影响后续 item。"""
        llm_result = {
            "foreshadows": [
                {"description": "item A"},
                {"description": "item B"},
            ]
        }
        pipeline = MagicMock()
        pipeline._build_foreshadow_payload = MagicMock(
            side_effect=lambda idx, desc: {"description": desc}
        )
        # 第一次抛异常，第二次正常
        pipeline._persist_foreshadow_payload = MagicMock(
            side_effect=[Exception("DB down"), None]
        )
        pipeline.foreshadow_service = MagicMock()

        with _patched_call_llm(llm_result):
            saved = await extract_and_persist(
                chapter_idx=0, chapter_text="x", pipeline=pipeline
            )

        # 只有 item B 落库成功
        assert saved == 1

    @pytest.mark.asyncio
    async def test_pipeline_without_methods_uses_fallback_payload(self):
        """pipeline 没有 _build_foreshadow_payload → 走内联 payload。"""
        llm_result = {"foreshadows": [{"description": "x"}]}
        pipeline = MagicMock(spec=[])  # 没有 _build_foreshadow_payload 属性
        pipeline.foreshadow_service = MagicMock()
        pipeline._persist_foreshadow_payload = MagicMock()

        with _patched_call_llm(llm_result):
            saved = await extract_and_persist(
                chapter_idx=2, chapter_text="x", pipeline=pipeline
            )

        assert saved == 1
        # 验证内联 payload 含必要字段
        call_args = pipeline._persist_foreshadow_payload.call_args
        payload = call_args.args[1]
        assert payload["status"] == "active"
        assert payload["source"] == "llm_extract"
