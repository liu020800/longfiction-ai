import pytest
from core.llm_router import (
    strip_reasoning_artifacts,
    clamp_temperature,
    TaskType,
)


def test_strip_think_tag():
    input_text = "<think>这是推理过程</think>这是正文内容"
    result = strip_reasoning_artifacts(input_text)
    assert "推理" not in result
    assert "正文内容" in result


def test_strip_thinking_tag():
    input_text = "<thinking>深度思考</thinking>实际输出"
    result = strip_reasoning_artifacts(input_text)
    assert "深度思考" not in result
    assert "实际输出" in result


def test_strip_reasoning_tag():
    input_text = "<reasoning>推理内容</reasoning>正文输出"
    result = strip_reasoning_artifacts(input_text)
    assert "推理内容" not in result
    assert "正文输出" in result


def test_strip_code_block_thinking():
    input_text = "```thinking\n思考过程\n```\n正文内容"
    result = strip_reasoning_artifacts(input_text)
    assert "思考过程" not in result
    assert "正文内容" in result


def test_strip_english_prefix():
    input_text = "According to my analysis, this is the result.\n正文内容"
    result = strip_reasoning_artifacts(input_text)
    assert "According to my analysis" not in result
    assert "正文内容" in result


def test_strip_mixed_reasoning():
    input_text = "<think>思考</think>正文1<reasoning>推理</reasoning>正文2"
    result = strip_reasoning_artifacts(input_text)
    assert "思考" not in result
    assert "推理" not in result
    assert "正文1" in result
    assert "正文2" in result


def test_strip_no_reasoning():
    input_text = "这是一段没有任何推理标记的正文内容"
    result = strip_reasoning_artifacts(input_text)
    assert result == input_text


def test_clamp_temperature_write():
    assert clamp_temperature(TaskType.WRITE, 0.8) == 0.8
    assert clamp_temperature(TaskType.WRITE, 0.5) == 0.7
    assert clamp_temperature(TaskType.WRITE, 1.0) == 0.95


def test_clamp_temperature_check():
    assert clamp_temperature(TaskType.CHECK, 0.4) == 0.4
    assert clamp_temperature(TaskType.CHECK, 0.1) == 0.3
    assert clamp_temperature(TaskType.CHECK, 0.8) == 0.5


def test_clamp_temperature_plan():
    assert clamp_temperature(TaskType.PLAN, 0.4) == 0.4
    assert clamp_temperature(TaskType.PLAN, 0.1) == 0.3
    assert clamp_temperature(TaskType.PLAN, 0.7) == 0.5


def test_clamp_temperature_rewrite():
    assert clamp_temperature(TaskType.REWRITE, 0.65) == 0.65
    assert clamp_temperature(TaskType.REWRITE, 0.2) == 0.5
    assert clamp_temperature(TaskType.REWRITE, 0.9) == 0.8
