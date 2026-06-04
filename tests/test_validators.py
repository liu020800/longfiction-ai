"""测试 core.validators 模块。"""
import pytest
from pydantic import BaseModel

from core.validators import (
    parse_json,
    parse_json_strict,
    parse_json_lenient,
    validate_with_model,
    parse_json_with_model,
    validate_chapter_content,
    validate_title,
    extract_json_block,
    debug_parse_failure,
)


class TestParseJsonStrict:
    def test_valid_json(self):
        result = parse_json_strict('{"a": 1, "b": "x"}')
        assert result.success
        assert result.value == {"a": 1, "b": "x"}

    def test_invalid_json(self):
        result = parse_json_strict('{"a": 1,}')
        assert not result.success
        assert result.error is not None


class TestParseJsonLenient:
    def test_empty_input(self):
        result = parse_json_lenient("")
        assert not result.success

    def test_direct_parse(self):
        result = parse_json_lenient('{"a": 1}')
        assert result.success
        assert result.value == {"a": 1}

    def test_code_fence(self):
        text = '```json\n{"a": 1}\n```'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": 1}

    def test_bare_code_fence(self):
        text = '```\n{"a": 1}\n```'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": 1}

    def test_thinking_block_removed(self):
        text = '<think>Let me think</think>{"a": 1}'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": 1}

    def test_trailing_comma(self):
        text = '{"a": 1, "b": 2,}'
        result = parse_json_lenient(text)
        assert result.success
        assert result.recovered
        assert result.value == {"a": 1, "b": 2}

    def test_unquoted_keys(self):
        text = '{a: 1, b: 2}'
        result = parse_json_lenient(text)
        assert result.success
        assert result.recovered
        assert result.value == {"a": 1, "b": 2}

    def test_newline_in_string(self):
        text = '{"a": "line1\nline2"}'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": "line1\nline2"}

    def test_smart_quotes(self):
        text = '\u201c{"a": 1}\u201d'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": 1}

    def test_nested_json(self):
        text = '```json\n{"a": {"b": [1, 2, 3]}}\n```'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": {"b": [1, 2, 3]}}

    def test_extraction_from_messy(self):
        text = 'Here is the JSON:\n```json\n{"a": 1}\n```\nHope it helps!'
        result = parse_json_lenient(text)
        assert result.success
        assert result.value == {"a": 1}


class TestValidateWithModel:
    def test_valid(self):
        class M(BaseModel):
            a: int
            b: str
        m = validate_with_model({"a": 1, "b": "x"}, M)
        assert m.a == 1
        assert m.b == "x"

    def test_invalid_raises(self):
        class M(BaseModel):
            a: int
        with pytest.raises(ValueError, match="Validation failed"):
            validate_with_model({"a": "not_an_int"}, M)


class TestParseJsonWithModel:
    def test_success(self):
        class M(BaseModel):
            a: int
        result, err = parse_json_with_model('{"a": 42}', M)
        assert result is not None
        assert result.a == 42
        assert err is None

    def test_validation_error(self):
        class M(BaseModel):
            a: int
        result, err = parse_json_with_model('{"a": "x"}', M)
        assert result is None
        assert err is not None


class TestContentValidation:
    def test_valid_content(self):
        ok, reason = validate_chapter_content("x" * 200, min_length=100)
        assert ok
        assert reason == "ok"

    def test_empty_content(self):
        ok, reason = validate_chapter_content("", min_length=100)
        assert not ok
        assert "空" in reason

    def test_too_short(self):
        ok, reason = validate_chapter_content("short", min_length=100)
        assert not ok
        assert "过短" in reason

    def test_valid_title(self):
        ok, reason = validate_title("第一章 觉醒")
        assert ok

    def test_empty_title(self):
        ok, reason = validate_title("")
        assert not ok

    def test_too_long_title(self):
        ok, reason = validate_title("x" * 200)
        assert not ok


class TestExtractJsonBlock:
    def test_from_code_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert extract_json_block(text) == '{"a": 1}'

    def test_from_bare_json(self):
        text = 'prefix {"a": 1} suffix'
        result = extract_json_block(text)
        assert result is not None
        assert '{"a": 1}' in result

    def test_no_json(self):
        text = 'no json here'
        assert extract_json_block(text) is None


class TestDebugParseFailure:
    def test_basic(self):
        info = debug_parse_failure('<think>...</think>{"a": 1}')
        assert "thinking_blocks_found" in info
        assert info["thinking_blocks_found"] is True
        assert "brace_count_open" in info
