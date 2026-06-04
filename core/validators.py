"""JSON 解析与数据验证工具。

增强 LLM 输出的 JSON 解析容错能力。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class ParseResult:
    """解析结果。"""
    success: bool
    value: Any = None
    error: Optional[str] = None
    recovered: bool = False  # 是否经过修复
    strategy: str = "exact"  # 使用的解析策略


# ============== JSON 修复工具 ==============

def _strip_code_fence(text: str) -> str:
    """剥离 markdown 代码块标记。"""
    text = text.strip()
    # ```json ... ```
    m = re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 裸 ``` 包裹
    m = re.search(r"```(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _strip_thinking_blocks(text: str) -> str:
    """剥离推理/思考块（DeepSeek-R1 等模型会输出）。"""
    # 剥离 <think>...</think>
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking\b[^>]*>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 剥离 ```{thinking}...```
    text = re.sub(r"```(?:thinking|reasoning|analysis)\s*\n?.*?\n?```", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _find_json_boundaries(text: str) -> Optional[tuple[int, int]]:
    """查找 JSON 对象的开始和结束位置。"""
    # 找到第一个 { 或 [
    starts = [i for i, ch in enumerate(text) if ch in "{["]
    if not starts:
        return None
    start = starts[0]
    # 找到匹配的 } 或 ]
    open_count = 0
    in_string = False
    escape_next = False
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            open_count += 1
        elif ch == close_ch:
            open_count -= 1
            if open_count == 0:
                return (start, i)
    return None


def _fix_trailing_comma(text: str) -> str:
    """修复 JSON 中的尾随逗号。"""
    # 移除 ,] 或 ,} 这种尾随逗号
    text = re.sub(r",\s*([\]\}])", r"\1", text)
    return text


def _fix_unquoted_keys(text: str) -> str:
    """修复未加引号的 JSON key（仅处理简单的 key 形式）。"""
    # 匹配 {"key": 这种结构的 key 部分
    # 仅处理 key 是合法标识符的情况
    pattern = re.compile(r'([\{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:')
    return pattern.sub(r'\1"\2":', text)


def _fix_single_quotes(text: str) -> str:
    """修复单引号字符串为双引号。"""
    # 简单替换：把 'xxx' 转为 "xxx"
    # 注意：这只在 LLM 输出确实错误使用单引号时才有意义
    # 风险：内容包含撇号会误伤。需要先识别 JSON 边界
    # 简化为：仅在明显是 JSON 字符串边界时替换
    return re.sub(r"'([^'\n]*)'", r'"\1"', text)


def _escape_newlines_in_strings(text: str) -> str:
    """转义字符串内的裸换行符。

    LLM 经常在 JSON 字符串中输出真正的换行符，这是不合法的。
    """
    # 找到 "..." 字符串，对内部的真实换行做转义
    out = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch == "\n":
            out.append("\\n")
            continue
        if in_string and ch == "\r":
            out.append("\\r")
            continue
        if in_string and ch == "\t":
            out.append("\\t")
            continue
        out.append(ch)
    return "".join(out)


def _remove_comments(text: str) -> str:
    """移除 JSON 中的 // 和 /* */ 注释。"""
    # /* ... */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # // ...
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _normalize_unicode_quotes(text: str) -> str:
    """将中文/智能引号统一为标准引号。"""
    return (
        text
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


# ============== 主解析函数 ==============

def parse_json_strict(text: str) -> ParseResult:
    """严格 JSON 解析（不修复）。"""
    try:
        return ParseResult(success=True, value=json.loads(text), strategy="strict")
    except json.JSONDecodeError as e:
        return ParseResult(success=False, error=str(e), strategy="strict")


def parse_json_lenient(text: str) -> ParseResult:
    """宽松 JSON 解析（多种修复策略）。

    依次尝试：
    1. 剥离思考块
    2. 剥离代码块标记
    3. 标准化引号
    4. 严格解析
    5. 在原文寻找 JSON 边界再解析
    6. 修复常见错误（尾随逗号、未加引号 key、单引号、字符串内换行）
    7. 再次严格解析
    """
    if not text:
        return ParseResult(success=False, error="Empty input", strategy="lenient")

    original = text
    text = _strip_thinking_blocks(text)
    text = _strip_code_fence(text)
    text = _normalize_unicode_quotes(text)
    text = text.strip()

    # 策略 1: 直接解析
    try:
        return ParseResult(success=True, value=json.loads(text), strategy="direct")
    except json.JSONDecodeError:
        pass

    # 策略 2: 寻找 JSON 边界
    boundaries = _find_json_boundaries(text)
    if boundaries:
        start, end = boundaries
        candidate = text[start:end + 1]
        try:
            return ParseResult(
                success=True,
                value=json.loads(candidate),
                recovered=True,
                strategy="boundary_extract",
            )
        except json.JSONDecodeError:
            pass

    # 策略 3: 移除注释 + 修复尾随逗号
    fixed = _remove_comments(text)
    fixed = _fix_trailing_comma(fixed)
    try:
        return ParseResult(
            success=True,
            value=json.loads(fixed),
            recovered=True,
            strategy="fix_comments_trailing",
        )
    except json.JSONDecodeError:
        pass

    # 策略 4: 修复未加引号 key
    fixed2 = _fix_unquoted_keys(fixed)
    try:
        return ParseResult(
            success=True,
            value=json.loads(fixed2),
            recovered=True,
            strategy="fix_unquoted_keys",
        )
    except json.JSONDecodeError:
        pass

    # 策略 5: 修复字符串内换行
    fixed3 = _escape_newlines_in_strings(fixed2)
    try:
        return ParseResult(
            success=True,
            value=json.loads(fixed3),
            recovered=True,
            strategy="fix_newlines",
        )
    except json.JSONDecodeError:
        pass

    # 策略 6: 修复单引号
    fixed4 = _fix_single_quotes(fixed3)
    try:
        return ParseResult(
            success=True,
            value=json.loads(fixed4),
            recovered=True,
            strategy="fix_single_quotes",
        )
    except json.JSONDecodeError as e:
        return ParseResult(
            success=False,
            error=f"All strategies failed. Last error: {e}",
            strategy="all_failed",
        )


def parse_json(text: str, lenient: bool = True) -> ParseResult:
    """统一的 JSON 解析入口。

    Args:
        text: 待解析的文本
        lenient: 是否使用宽松模式

    Returns:
        ParseResult
    """
    if lenient:
        return parse_json_lenient(text)
    return parse_json_strict(text)


def validate_with_model(data: Any, model_class: Type[T]) -> T:
    """使用 Pydantic 模型验证数据。

    Args:
        data: 待验证的数据（通常是解析后的 dict/list）
        model_class: 目标 Pydantic 模型类

    Returns:
        验证后的模型实例

    Raises:
        ValueError: 验证失败
    """
    try:
        return model_class.model_validate(data)
    except ValidationError as e:
        # 提供更详细的错误信息
        errors = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        raise ValueError(f"Validation failed for {model_class.__name__}: {'; '.join(errors)}")


def parse_json_with_model(
    text: str,
    model_class: Type[T],
    lenient: bool = True,
) -> tuple[Optional[T], Optional[str]]:
    """解析 JSON 并直接验证为 Pydantic 模型。

    Args:
        text: LLM 输出的 JSON 文本
        model_class: 目标模型
        lenient: 是否宽松解析

    Returns:
        (model_instance, error_message)
    """
    result = parse_json(text, lenient=lenient)
    if not result.success:
        return None, result.error
    try:
        return validate_with_model(result.value, model_class), None
    except ValueError as e:
        return None, str(e)


def extract_json_block(text: str) -> Optional[str]:
    """从文本中提取 JSON 代码块（不解析）。"""
    text = _strip_thinking_blocks(text)
    # 优先匹配 ```json ... ```
    m = re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 其次匹配裸 JSON
    boundaries = _find_json_boundaries(text)
    if boundaries:
        start, end = boundaries
        return text[start:end + 1]
    return None


# ============== 内容验证 ==============

def validate_chapter_content(content: str, min_length: int = 100) -> tuple[bool, str]:
    """验证章节内容。

    Args:
        content: 章节内容
        min_length: 最小字符数

    Returns:
        (is_valid, reason)
    """
    if not content:
        return False, "内容为空"
    content = content.strip()
    if len(content) < min_length:
        return False, f"内容过短（{len(content)} < {min_length} 字符）"
    return True, "ok"


def validate_title(title: str) -> tuple[bool, str]:
    """验证章节标题。"""
    if not title or not title.strip():
        return False, "标题为空"
    title = title.strip()
    if len(title) < 2:
        return False, "标题过短（< 2 字符）"
    if len(title) > 100:
        return False, "标题过长（> 100 字符）"
    return True, "ok"


# ============== 调试辅助 ==============

def debug_parse_failure(text: str) -> dict:
    """生成解析失败的调试信息。"""
    return {
        "input_length": len(text),
        "input_preview": text[:500],
        "input_suffix": text[-200:] if len(text) > 500 else "",
        "thinking_blocks_found": bool(re.search(r"<think", text, re.IGNORECASE)),
        "code_fence_found": "```" in text,
        "smart_quotes_found": any(c in text for c in "\u201c\u201d\u2018\u2019"),
        "brace_count_open": text.count("{"),
        "brace_count_close": text.count("}"),
    }
