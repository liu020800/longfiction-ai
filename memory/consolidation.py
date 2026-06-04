"""记忆整合。

定期将分散的记忆整合为更结构化的形式：
- 短期记忆 → 结构化记忆
- 散乱的事实 → 关系图谱
- 旧的长期记忆 → 分层摘要
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from memory.working_memory import WorkingMemory
from memory.relationship_graph import RelationshipGraph, RelationType

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """整合结果。"""
    facts_extracted: int = 0
    relations_updated: int = 0
    events_recorded: int = 0
    working_memory_items: int = 0
    errors: list[str] = field(default_factory=list)


class MemoryConsolidator:
    """记忆整合器。

    定期执行整合操作，将短期/工作记忆中的信息沉淀到长期结构。
    """

    def __init__(
        self,
        working_memory: Optional[WorkingMemory] = None,
        relationship_graph: Optional[RelationshipGraph] = None,
        structured_memory=None,  # StructuredMemory 实例
    ):
        self.working = working_memory or WorkingMemory()
        self.graph = relationship_graph or RelationshipGraph()
        self.structured = structured_memory

    async def consolidate_chapter(
        self,
        chapter_index: int,
        chapter_content: str,
        chapter_summary: str,
    ) -> ConsolidationResult:
        """整合一章内容的记忆。"""
        import asyncio
        result = ConsolidationResult()

        try:
            # 1. 工作记忆统计
            result.working_memory_items = len(self.working)

            # 2. 从章节内容中提取关系
            relations = await self._extract_relations(
                chapter_content, chapter_summary, chapter_index
            )
            for rel in relations:
                self.graph.add_relation(
                    source=rel["source"],
                    target=rel["target"],
                    relation_type=RelationType(rel["type"]),
                    description=rel.get("description", ""),
                    strength=rel.get("strength", 5),
                    chapter=chapter_index,
                )
            result.relations_updated = len(relations)

            # 3. 提取关键事实
            facts = await self._extract_facts(chapter_content, chapter_summary)
            result.facts_extracted = len(facts)

            # 4. 写入结构化记忆
            if self.structured is not None and facts:
                for fact in facts:
                    try:
                        # 这里假设 structured 有相应方法
                        if hasattr(self.structured, "add_fact"):
                            self.structured.add_fact(chapter_index, fact)
                    except Exception as e:
                        result.errors.append(f"add_fact: {e}")

            # 5. 清空工作记忆
            self.working.clear()

        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            result.errors.append(str(e))

        return result

    async def _extract_relations(
        self,
        content: str,
        summary: str,
        chapter_index: int,
    ) -> list[dict]:
        """使用 LLM 提取章节中的角色关系。"""
        # 这里使用简单的正则方法 + LLM 调用
        from core.llm_router import call_llm, TaskType
        prompt = (
            f"从以下小说章节中提取所有角色之间的关系。\n\n"
            f"## 章节内容（前 2000 字）\n{content[:2000]}\n\n"
            f"## 摘要\n{summary}\n\n"
            f"输出 JSON 数组，每个元素：\n"
            f'{{"source": "角色A", "target": "角色B", "type": "关系类型", '
            f'"description": "关系描述", "strength": 1-10}}\n\n'
            f"关系类型可选：family, romantic, friend, enemy, mentor, rival, ally, subordinate, neutral\n\n"
            f"如果没有明确关系，输出 []。"
        )
        try:
            response = await call_llm(
                TaskType.PLAN, prompt, temperature=0.2, json_mode=True
            )
            if isinstance(response, list):
                return response
            if isinstance(response, dict):
                return response.get("relations", [])
        except Exception as e:
            logger.warning(f"Relation extraction failed: {e}")
        return []

    async def _extract_facts(self, content: str, summary: str) -> list[str]:
        """从章节中提取关键事实。"""
        from core.llm_router import call_llm, TaskType
        prompt = (
            f"从以下小说章节中提取关键事实（人物状态变化、新设定、关键事件等）。\n\n"
            f"## 章节摘要\n{summary}\n\n"
            f"输出 JSON 数组，每个元素是一句话事实：\n"
            f'["主角林远获得了青云剑法", "青云宗宗主更换为张三", ...]'
        )
        try:
            response = await call_llm(
                TaskType.PLAN, prompt, temperature=0.2, json_mode=True
            )
            if isinstance(response, list):
                return response
        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
        return []
