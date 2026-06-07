"""P1-4: 记忆上下文桥接。

把 MemorySystem 内分散的存储（structured / short_term / working / relationship_graph / long_term）
统一拼装为一段供 writer prompt 注入的文本，并对每个子存储独立 try/except，
避免"FAISS 有数据但结构化卡崩溃 → 整段上下文丢失"。

设计目标：
1. **容错**：每个子存储独立查询，单一失败不影响整体
2. **完整**：同时查询结构化记忆 / 工作记忆 / 角色关系 / 最近上下文 / FAISS 相似记忆
3. **可控**：限制总长度（默认 2500 字），保留前面的优先信息
4. **轻量**：默认同步版本不触发 LLM embedding；异步版本可选启用 FAISS

不会重写任何已有 store 实现，只复用：
- `memory.structured.get_character_profiles_text()`
- `memory.structured.get_world_text()`
- `memory.short_term.get_context_for_writer()`
- `memory.working_memory.get_context_text()`
- `memory.relationship_graph.get_context_text()`
- `await memory.rag.get_embedding(text)`（异步版本）
- `memory.long_term.search(embedding, top_k)`（异步版本）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 各段位最大字符数（防止单段塞满整个 max_chars）
_SECTION_LIMITS = {
    "structured_world": 800,
    "structured_chars": 1200,
    "relationships": 600,
    "working": 500,
    "recent": 900,
    "faiss": 900,
}


def _safe_call(label: str, fn, *args, **kwargs) -> str:
    """同步包装：调用子存储方法，单一失败不抛异常。"""
    try:
        result = fn(*args, **kwargs)
        if not result:
            return ""
        return str(result)
    except Exception as exc:
        logger.warning(f"[context_bridge] {label} failed: {exc}")
        return ""


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def build_memory_context(
    memory: Any,
    chapter_index: int = 0,
    query: str = "",
    max_chars: int = 2500,
    include_world: bool = True,
    include_characters: bool = True,
    include_relationships: bool = True,
    include_working: bool = True,
    include_recent: bool = True,
) -> str:
    """同步组装记忆上下文。

    Args:
        memory: MemorySystem 实例（可为 None，返回空串）
        chapter_index: 当前章节号（仅用于日志/查询参考）
        query: 可选查询关键字（同步版本不触发 FAISS）
        max_chars: 总长度上限
        include_*: 各段位开关

    Returns:
        拼装后的上下文文本（≤ max_chars）。若所有 store 都失败，返回空串。
    """
    if memory is None:
        return ""

    sections: list[str] = []

    # 1. 世界观（settings、cultivation_system 等）
    if include_world and getattr(memory, "structured", None) is not None:
        world_text = _safe_call(
            "structured.get_world_text",
            memory.structured.get_world_text,
        )
        if world_text:
            sections.append(
                "【世界观】\n" + _truncate(world_text, _SECTION_LIMITS["structured_world"])
            )

    # 2. 角色档案（profile + 状态）
    if include_characters and getattr(memory, "structured", None) is not None:
        chars_text = _safe_call(
            "structured.get_character_profiles_text",
            memory.structured.get_character_profiles_text,
        )
        if chars_text:
            sections.append(
                "【角色档案】\n" + _truncate(chars_text, _SECTION_LIMITS["structured_chars"])
            )

    # 3. 角色关系
    if include_relationships and getattr(memory, "relationship_graph", None) is not None:
        rel_text = _safe_call(
            "relationship_graph.get_context_text",
            memory.relationship_graph.get_context_text,
        )
        if rel_text:
            sections.append(
                "【角色关系】\n" + _truncate(rel_text, _SECTION_LIMITS["relationships"])
            )

    # 4. 工作记忆（当前场景上下文）
    if include_working and getattr(memory, "working_memory", None) is not None:
        wm_text = _safe_call(
            "working_memory.get_context_text",
            memory.working_memory.get_context_text,
        )
        if wm_text:
            sections.append(
                "【工作记忆】\n" + _truncate(wm_text, _SECTION_LIMITS["working"])
            )

    # 5. 最近章节上下文
    if include_recent and getattr(memory, "short_term", None) is not None:
        recent = _safe_call(
            "short_term.get_context_for_writer",
            memory.short_term.get_context_for_writer,
        )
        if recent:
            sections.append(
                "【最近上下文】\n" + _truncate(recent, _SECTION_LIMITS["recent"])
            )

    full = "\n\n".join(sections)
    if max_chars and len(full) > max_chars:
        # 保留前面的高优先级内容
        full = full[:max_chars] + "\n...(上下文已截断)"
    return full


async def build_memory_context_with_rag(
    memory: Any,
    chapter_index: int = 0,
    query: str = "",
    top_k: int = 5,
    max_chars: int = 3000,
) -> str:
    """异步版本：在同步版本基础上追加 FAISS 相似记忆段。

    需要 `memory.rag.get_embedding(text)` 和 `memory.long_term.search(emb, top_k)`。
    若 RAG/FAISS 不可用，自动降级为同步结果。

    Args:
        query: 用于嵌入的查询语句，空时使用"第N章"作为默认。
        top_k: FAISS 检索条数。
    """
    base = build_memory_context(
        memory=memory,
        chapter_index=chapter_index,
        query=query,
        max_chars=max_chars,  # 此处不强限制，后面会再次裁剪
    )

    if memory is None:
        return base

    rag = getattr(memory, "rag", None)
    long_term = getattr(memory, "long_term", None)
    if rag is None or long_term is None:
        return base

    query_text = query.strip() or f"第{chapter_index + 1}章 相关情节"
    try:
        embedding = await rag.get_embedding(query_text)
    except Exception as exc:
        logger.warning(f"[context_bridge] rag.get_embedding failed: {exc}")
        return base

    try:
        results = long_term.search(embedding, top_k=top_k)
    except Exception as exc:
        logger.warning(f"[context_bridge] long_term.search failed: {exc}")
        return base

    if not results:
        return base

    items: list[str] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        text = str(r.get("text", "")).strip()
        if text:
            items.append(f"- {text}")
    if not items:
        return base

    rag_section = "【相似记忆】\n" + _truncate(
        "\n".join(items), _SECTION_LIMITS["faiss"]
    )
    combined = base + ("\n\n" if base else "") + rag_section
    if max_chars and len(combined) > max_chars:
        combined = combined[:max_chars] + "\n...(上下文已截断)"
    return combined
