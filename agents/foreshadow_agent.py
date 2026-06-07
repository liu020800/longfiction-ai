"""P2-B：LLM 驱动的伏笔提取 agent。

**保留旧启发式**（`main_pipeline._derive_new_foreshadow_candidates`）作 fallback；
本模块提供 LLM 提取路径，对每章正文从 0~max_count 个真正值得保留的伏笔。

## 设计目标

1. **不删除** 任何已有伏笔逻辑；本模块是"补充"而非"替代"
2. **失败安全**：LLM 调用异常 / JSON 解析失败 / 字段类型错，**全部** 返回 `[]`，绝不抛异常影响主流程
3. **容错字段**：所有 LLM 返回字段做 `isinstance + str/int 转换`，避免上游 1 个字段类型错污染整章
4. **可测试**：纯函数 `extract_foreshadows` 不依赖任何 DB / pipeline 状态，方便单测
5. **轻量**：不引入新依赖；复用项目标配的 `call_llm(TaskType.CHECK, ..., json_mode=True)`

## 关键不变性

- 本模块不修改 `main_pipeline.py` 的启发式代码
- LLM 失败 → `[]`，caller 继续走启发式
- 任何 LLM 字段类型异常 → 容错（默认 1 / 5 / 30 等）
- 不修改 `Foreshadowing` 数据模型

## 用法

```python
from agents.foreshadow_agent import extract_foreshadows, extract_and_persist

# 纯函数：只提取不落库
items = await extract_foreshadows(chapter_text=..., chapter_index=3)

# 便利函数：提取并通过 pipeline._persist_foreshadow_payload 落库
saved = await extract_and_persist(chapter_idx=3, chapter_text=..., pipeline=...)
```
"""
from __future__ import annotations

import logging
from typing import Any

from core.llm_router import TaskType, call_llm

logger = logging.getLogger(__name__)


_PROMPT_PREFIX = (
    "你是长篇小说伏笔编辑。请从下方第 N 章正文中提取真正值得保留的伏笔（最多 5 个）。\n"
    "要求：\n"
    "1) 普通设定 / 日常动作 / 一次性事件 不算伏笔；\n"
    "2) 必须有未来回收价值（揭示真相、触发反转、连接人物关系等）；\n"
    "3) 不确定就少提取，宁缺毋滥。\n\n"
    "请严格按如下 JSON 格式输出（不要任何额外说明文字）：\n"
    "{\n"
    '  "foreshadows": [\n'
    "    {\n"
    '      "description": "一句话描述伏笔内容",\n'
    '      "visible_clue": "读者可见的线索（原文片段或改写）",\n'
    '      "hidden_truth": "伏笔隐藏的真相 / 未来揭示方向",\n'
    '      "importance": 1-5,\n'
    '      "expected_payoff_after": 5,\n'
    '      "expected_payoff_before": 30,\n'
    '      "related_characters": ["角色A", "角色B"],\n'
    '      "keywords": ["关键词1", "关键词2"]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "【本章正文】\n"
)

_SYSTEM_PROMPT = "你只能输出严格 JSON，不要解释、不要 Markdown 围栏、不要多余文字。"


def _safe_int(value: Any, default: int) -> int:
    """容错地把任意值转 int；失败返回 default。"""
    if isinstance(value, bool):  # bool 是 int 的子类，需排除
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _safe_str_list(value: Any) -> list[str]:
    """容错地把任意值转 list[str]；非 list / 元素非 str 都丢掉。"""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
        elif item is not None:
            # 数字 / 布尔等转字符串
            out.append(str(item))
    return out


def _normalize_item(raw: Any, max_count: int, idx: int) -> dict | None:
    """把 LLM 返回的 1 个伏笔 dict 标准化为内部 schema。

    字段类型错 / 缺失都容错；description 为空直接丢弃。
    """
    if not isinstance(raw, dict):
        return None

    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        return None

    return {
        "description": description.strip(),
        "visible_clue": (
            str(raw.get("visible_clue", "")).strip()
            if raw.get("visible_clue") is not None
            else ""
        ),
        "hidden_truth": (
            str(raw.get("hidden_truth", "")).strip()
            if raw.get("hidden_truth") is not None
            else ""
        ),
        "importance": _safe_int(raw.get("importance"), 1),
        "expected_payoff_after": _safe_int(raw.get("expected_payoff_after"), 5),
        "expected_payoff_before": _safe_int(raw.get("expected_payoff_before"), 30),
        "related_characters": _safe_str_list(raw.get("related_characters")),
        "keywords": _safe_str_list(raw.get("keywords")),
        "source": "llm_extract",
        "foreshadow_type": "clue",
        # idx 留给调试；不在最终 schema 里使用
        "_extract_order": idx,
    }


async def extract_foreshadows(
    chapter_text: str,
    chapter_index: int = 0,
    max_count: int = 5,
    max_input_chars: int = 6000,
) -> list[dict]:
    """用 LLM 从章节正文提取 0~max_count 个伏笔。

    Args:
        chapter_text: 章节正文（超过 `max_input_chars` 会被截断到前 N 字）
        chapter_index: 当前章节号（仅用于 prompt / 日志；不影响输出）
        max_count: 最多返回条数（默认 5；与 plan §9.1 一致）
        max_input_chars: 输入 prompt 的最大字符数（默认 6000）

    Returns:
        标准化后的伏笔 list。**任何** 失败都返回 `[]`，绝不抛异常。
    """
    if not chapter_text or not str(chapter_text).strip():
        return []
    if max_count <= 0:
        return []

    truncated = str(chapter_text)[:max_input_chars]
    prompt = _PROMPT_PREFIX.replace("第 N 章", f"第{chapter_index + 1}章") + truncated

    try:
        result = await call_llm(
            TaskType.CHECK,
            prompt=prompt,
            system=_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=1200,
            json_mode=True,
        )
    except Exception as exc:
        logger.warning(
            f"[foreshadow_agent] LLM call failed (chapter {chapter_index}): {exc}"
        )
        return []

    if not isinstance(result, dict):
        logger.warning(
            f"[foreshadow_agent] LLM returned non-dict (chapter {chapter_index}): "
            f"type={type(result).__name__}"
        )
        return []

    items = result.get("foreshadows")
    if not isinstance(items, list):
        # 没有 foreshadows 字段或类型错 → 视为"未提取出伏笔"
        if "foreshadows" in result:
            logger.warning(
                f"[foreshadow_agent] 'foreshadows' is not a list (chapter {chapter_index}): "
                f"{type(items).__name__}"
            )
        return []

    out: list[dict] = []
    for idx, raw in enumerate(items[:max_count]):
        try:
            normalized = _normalize_item(raw, max_count, idx)
        except Exception as exc:
            logger.warning(
                f"[foreshadow_agent] item {idx} normalization failed: {exc}"
            )
            continue
        if normalized is not None:
            out.append(normalized)

    if len(items) > max_count:
        logger.info(
            f"[foreshadow_agent] chapter {chapter_index} had {len(items)} candidates, "
            f"capped to {max_count}"
        )

    return out


async def extract_and_persist(
    chapter_idx: int,
    chapter_text: str,
    pipeline: Any,
    max_count: int = 5,
) -> int:
    """便利函数：调用 `extract_foreshadows` 然后通过 pipeline 落库。

    Returns:
        成功持久化的条数。0 表示 LLM 未提取出有效伏笔或全部 persist 失败。

    Notes:
        - 调用方应自行 try/except 包本函数（虽然内部已 catch，但 caller 拿不到失败原因）
        - 不修改 `main_pipeline._persist_foreshadow_payload` 签名
    """
    items = await extract_foreshadows(
        chapter_text=chapter_text,
        chapter_index=chapter_idx,
        max_count=max_count,
    )
    if not items:
        return 0

    saved = 0
    for item in items:
        # 复用现有 _build_foreshadow_payload 标准化路径
        # 若该方法不存在或签名不同，回退到内联 payload 构造
        payload = None
        try:
            if hasattr(pipeline, "_build_foreshadow_payload"):
                # _build_foreshadow_payload 接受 (chapter_idx, cleaned_text)
                payload = pipeline._build_foreshadow_payload(
                    chapter_idx, item.get("description", "")
                )
        except Exception as exc:
            logger.warning(
                f"[foreshadow_agent] _build_foreshadow_payload failed, using fallback: {exc}"
            )
            payload = None

        if not payload:
            payload = {
                "description": item["description"],
                "foreshadow_type": item.get("foreshadow_type", "clue"),
                "trigger_keywords": item.get("keywords", []),
                "payoff_condition": item.get("hidden_truth", ""),
                "source_excerpt": item.get("visible_clue", ""),
                "close_by_chapter": chapter_idx + item.get("expected_payoff_after", 5),
                "status": "active",
                "source": "llm_extract",
            }

        try:
            if hasattr(pipeline, "_persist_foreshadow_payload") and hasattr(
                pipeline, "foreshadow_service"
            ):
                pipeline._persist_foreshadow_payload(
                    pipeline.foreshadow_service, payload, chapter_idx
                )
                saved += 1
            else:
                logger.warning(
                    "[foreshadow_agent] pipeline missing _persist_foreshadow_payload "
                    "or foreshadow_service; skipping persist"
                )
                break
        except Exception as exc:
            logger.warning(
                f"[foreshadow_agent] persist failed (chapter {chapter_idx}): {exc}"
            )
            continue

    return saved


__all__ = ["extract_foreshadows", "extract_and_persist"]
