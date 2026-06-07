"""LLM 输出 JSON 解析与推理块剥离。

支持多种容错策略，按顺序尝试直到成功。
"""
from __future__ import annotations

import json
import re
from typing import Any


_REASONING_PREFIXES = [
    "According to my analysis",
    "Based on my analysis",
    "Let me analyze",
    "Let me think",
    "I'll analyze",
    "As I reason through this",
    "My reasoning:",
    "Analysis:",
    "我的分析",
    "分析如下",
    "让我分析",
    "让我想想",
]


def strip_reasoning_artifacts(content: str) -> str:
    """剥离 LLM 输出的推理/思考块。

    移除：
    - `<reasoning>...</reasoning>` 标签
    - `<think>...</think>` / `<thinking>...</thinking>` 标签
    - Markdown 推理围栏
    - 推理前缀行（"Let me think" / "我的分析" 等）
    """
    if not content:
        return ""

    text = str(content)

    text = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<thinking\b[^>]*>.*?</thinking>", "", text, flags=re.S | re.I)
    text = re.sub(r"```(?:thinking|reasoning)\s*.*?```", "", text, flags=re.S | re.I)

    if any(text.startswith(p) for p in _REASONING_PREFIXES) or any(
        text.lstrip().startswith(p) for p in _REASONING_PREFIXES
    ):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if any(stripped.startswith(p) for p in _REASONING_PREFIXES):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _remove_json_comments(text: str) -> str:
    """移除 `//` 和 `/* */` 注释。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _remove_trailing_commas(text: str) -> str:
    """移除 `,]` / `,}` 形式的尾随逗号。"""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _extract_json_boundary(text: str) -> str:
    """从文本中提取 JSON 围栏或裸 JSON 边界。"""
    fenced = re.search(r"```(?:json|JSON)?\s*(.*?)\s*```", text, flags=re.S | re.I)
    if fenced:
        return fenced.group(1).strip()

    start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not start_candidates:
        return text

    start = min(start_candidates)
    end_candidates = [idx for idx in (text.rfind("}"), text.rfind("]")) if idx != -1]
    if not end_candidates:
        return text
    end = max(end_candidates)
    if end <= start:
        return text
    return text[start:end + 1]


def _maybe_single_to_double_quotes(text: str) -> str:
    """兜底：仅在首部 20 字符内无 `"` 且有 `'` 时，替换单引号为双引号。"""
    if "'" in text and '"' not in text[:20]:
        return text.replace("'", '"')
    return text


def parse_llm_json(content: str) -> Any:
    """容错解析 LLM 输出的 JSON。

    依次尝试：
    1. 原始文本（先剥离推理块）
    2. 提取 ```json``` 围栏
    3. 移除 `//` 注释 + 移除尾随逗号
    4. 提取 `{...}` 或 `[...]` 边界
    5. （兜底）单引号换双引号
    """
    if not content:
        raise ValueError("LLM returned empty JSON response")

    text = strip_reasoning_artifacts(content)
    candidates: list[str] = []

    base = _extract_json_boundary(text)
    candidates.append(base)
    candidates.append(_remove_trailing_commas(_remove_json_comments(base)))
    candidates.append(_maybe_single_to_double_quotes(candidates[-1]))

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception as exc:
            last_error = exc

    raise ValueError(f"JSON 解析失败：{last_error}; raw={content[:500]}")
