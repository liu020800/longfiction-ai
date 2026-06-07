"""测试 core.llm_json 的容错解析能力。"""
import pytest

from core.llm_json import (
    parse_llm_json,
    strip_reasoning_artifacts,
)


class TestParseLlmJson:
    # ---- 策略 1：原始文本直接 parse ----
    def test_direct_valid_json(self):
        result = parse_llm_json('{"a": 1, "b": "x"}')
        assert result == {"a": 1, "b": "x"}

    def test_direct_valid_array(self):
        result = parse_llm_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_empty_input_raises(self):
        with pytest.raises(ValueError):
            parse_llm_json("")

    # ---- 策略 2：提取 ```json``` 围栏 ----
    def test_json_code_fence(self):
        content = '```json\n{"name": "test", "value": 42}\n```'
        result = parse_llm_json(content)
        assert result == {"name": "test", "value": 42}

    def test_json_code_fence_uppercase(self):
        content = '```JSON\n{"k": "v"}\n```'
        result = parse_llm_json(content)
        assert result == {"k": "v"}

    def test_code_fence_without_language_tag(self):
        content = '```\n{"a": 1}\n```'
        result = parse_llm_json(content)
        assert result == {"a": 1}

    # ---- 策略 3：移除 // 注释 + 尾随逗号 ----
    def test_json_with_line_comment(self):
        content = '{\n  "a": 1, // comment\n  "b": 2\n}'
        result = parse_llm_json(content)
        assert result == {"a": 1, "b": 2}

    def test_json_with_block_comment(self):
        content = '{"a": 1, /* note */ "b": 2}'
        result = parse_llm_json(content)
        assert result == {"a": 1, "b": 2}

    def test_json_with_trailing_comma(self):
        content = '{"a": 1, "b": 2,}'
        result = parse_llm_json(content)
        assert result == {"a": 1, "b": 2}

    def test_json_with_trailing_comma_in_array(self):
        content = '[1, 2, 3,]'
        result = parse_llm_json(content)
        assert result == [1, 2, 3]

    # ---- 策略 4：提取 {...} 边界 ----
    def test_json_embedded_in_text(self):
        content = 'Here is the result: {"status": "ok", "count": 5}. Hope that helps.'
        result = parse_llm_json(content)
        assert result == {"status": "ok", "count": 5}

    def test_json_array_embedded_in_text(self):
        content = 'Items are: [1, 2, 3] and that is all.'
        result = parse_llm_json(content)
        assert result == [1, 2, 3]

    # ---- 推理块剥离 ----
    def test_reasoning_block_stripped_before_parse(self):
        content = (
            "<think>\nLet me think about this carefully...\n"
            "I should output JSON.\n</think>\n"
            '{"answer": 42}'
        )
        result = parse_llm_json(content)
        assert result == {"answer": 42}

    def test_reasoning_tag_stripped(self):
        content = '<reasoning>some thoughts</reasoning>{"x": 1}'
        result = parse_llm_json(content)
        assert result == {"x": 1}

    def test_thinking_tag_stripped(self):
        content = '<thinking>analyzing...</thinking>{"y": 2}'
        result = parse_llm_json(content)
        assert result == {"y": 2}

    def test_chinese_reasoning_prefix_stripped(self):
        content = "我的分析：这是一个需要返回 JSON 的问题。\n{\"data\": \"ok\"}"
        result = parse_llm_json(content)
        assert result == {"data": "ok"}

    # ---- 兜底失败 ----
    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            parse_llm_json("this is not JSON at all")
        assert "JSON" in str(exc_info.value)

    def test_only_whitespace_raises(self):
        with pytest.raises(ValueError):
            parse_llm_json("   \n\t  ")

    def test_partial_json_raises(self):
        with pytest.raises(ValueError):
            parse_llm_json('{"incomplete":')

    def test_error_message_includes_excerpt(self):
        with pytest.raises(ValueError) as exc_info:
            parse_llm_json("garbage data here")
        # raw 字段应包含原始内容摘要
        assert "garbage" in str(exc_info.value)


class TestStripReasoningArtifacts:
    def test_empty_passes_through(self):
        assert strip_reasoning_artifacts("") == ""

    def test_plain_text_unchanged(self):
        text = "Just normal text without any reasoning."
        assert strip_reasoning_artifacts(text) == text

    def test_strips_think_block(self):
        text = "<think>hidden</think>visible"
        assert "visible" in strip_reasoning_artifacts(text)
        assert "hidden" not in strip_reasoning_artifacts(text)

    def test_strips_reasoning_block(self):
        text = "before <reasoning>deep thought</reasoning> after"
        result = strip_reasoning_artifacts(text)
        assert "deep thought" not in result
        assert "before" in result
        assert "after" in result

    def test_strips_thinking_block(self):
        text = "before <thinking>thoughts</thinking> after"
        result = strip_reasoning_artifacts(text)
        assert "thoughts" not in result

    def test_strips_markdown_reasoning_fence(self):
        text = "before ```thinking\nthoughts\n``` after"
        result = strip_reasoning_artifacts(text)
        assert "thoughts" not in result

    def test_strips_let_me_think_prefix(self):
        text = "Let me think about this.\nactual content"
        result = strip_reasoning_artifacts(text)
        assert "actual content" in result
        assert "Let me think" not in result

    def test_strips_chinese_analysis_prefix(self):
        text = "我的分析：\n实际内容"
        result = strip_reasoning_artifacts(text)
        assert "实际内容" in result
        assert "我的分析" not in result
