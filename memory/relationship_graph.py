"""角色关系图谱。

存储和管理角色之间的关系网络，支持关系查询、推理。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class RelationType(str, Enum):
    """关系类型。"""
    FAMILY = "family"           # 家族（父母、兄弟姐妹）
    ROMANTIC = "romantic"       # 恋爱
    FRIEND = "friend"           # 朋友
    ENEMY = "enemy"             # 敌对
    MENTOR = "mentor"           # 师徒
    RIVAL = "rival"             # 对手
    ALLY = "ally"               # 盟友
    SUBORDINATE = "subordinate" # 上下级
    NEUTRAL = "neutral"         # 中立


@dataclass
class Relation:
    """关系。"""
    source: str
    target: str
    relation_type: RelationType
    description: str = ""
    strength: int = 5            # 1-10, 10 = 最强
    bidirectional: bool = True   # 是否双向
    established_chapter: int = 0
    last_updated_chapter: int = 0
    history: list[str] = field(default_factory=list)  # 关系变化历史

    def update_strength(self, delta: int, chapter: int, reason: str = ""):
        """更新关系强度。"""
        self.strength = max(1, min(10, self.strength + delta))
        self.last_updated_chapter = chapter
        if reason:
            self.history.append(f"Ch{chapter}: {reason} (now {self.strength})")


class RelationshipGraph:
    """关系图谱。"""

    def __init__(self):
        self._relations: dict[tuple[str, str], Relation] = {}

    def add_relation(
        self,
        source: str,
        target: str,
        relation_type: RelationType,
        description: str = "",
        strength: int = 5,
        chapter: int = 0,
    ):
        """添加/更新关系。"""
        # 标准化 key（按字母序）
        key = tuple(sorted([source, target]))
        existing = self._relations.get(key)
        if existing:
            # 更新现有关系
            existing.relation_type = relation_type
            existing.description = description or existing.description
            existing.strength = strength
            existing.last_updated_chapter = chapter
        else:
            self._relations[key] = Relation(
                source=key[0],
                target=key[1],
                relation_type=relation_type,
                description=description,
                strength=strength,
                established_chapter=chapter,
                last_updated_chapter=chapter,
            )

    def get_relation(self, char_a: str, char_b: str) -> Optional[Relation]:
        """获取两个角色之间的关系。"""
        key = tuple(sorted([char_a, char_b]))
        return self._relations.get(key)

    def get_relations_of(self, char: str) -> list[Relation]:
        """获取某角色的所有关系。"""
        return [
            rel for rel in self._relations.values()
            if rel.source == char or rel.target == char
        ]

    def get_by_type(self, relation_type: RelationType) -> list[Relation]:
        """按类型查询关系。"""
        return [
            rel for rel in self._relations.values()
            if rel.relation_type == relation_type
        ]

    def get_strong_relations(self, threshold: int = 7) -> list[Relation]:
        """获取强关系（强度 >= threshold）。"""
        return [
            rel for rel in self._relations.values()
            if rel.strength >= threshold
        ]

    def get_characters(self) -> list[str]:
        """获取所有角色。"""
        chars = set()
        for rel in self._relations.values():
            chars.add(rel.source)
            chars.add(rel.target)
        return sorted(chars)

    def detect_contradiction(
        self,
        char_a: str,
        char_b: str,
        expected_type: RelationType,
    ) -> bool:
        """检测关系是否与期望矛盾。"""
        rel = self.get_relation(char_a, char_b)
        if rel is None:
            return False
        # 敌对 vs 朋友 是矛盾
        conflicting = {
            (RelationType.ENEMY, RelationType.FRIEND),
            (RelationType.ENEMY, RelationType.ALLY),
            (RelationType.FRIEND, RelationType.ENEMY),
            (RelationType.ALLY, RelationType.ENEMY),
            (RelationType.RIVAL, RelationType.MENTOR),
            (RelationType.MENTOR, RelationType.RIVAL),
        }
        return (rel.relation_type, expected_type) in conflicting

    def to_text(self) -> str:
        """转换为文本（用于 prompt 注入）。"""
        if not self._relations:
            return ""
        lines = ["## 角色关系\n"]
        # 按角色分组
        by_char: dict[str, list[Relation]] = {}
        for rel in self._relations.values():
            for c in [rel.source, rel.target]:
                by_char.setdefault(c, []).append(rel)
        for char in sorted(by_char.keys()):
            lines.append(f"### {char}")
            for rel in by_char[char]:
                other = rel.target if rel.source == char else rel.source
                lines.append(
                    f"  - {other} ({rel.relation_type.value}, 强度 {rel.strength}/10): {rel.description}"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "relations": [
                {
                    "source": r.source,
                    "target": r.target,
                    "type": r.relation_type.value,
                    "description": r.description,
                    "strength": r.strength,
                    "established_chapter": r.established_chapter,
                    "last_updated_chapter": r.last_updated_chapter,
                }
                for r in self._relations.values()
            ]
        }

    def clear(self):
        self._relations.clear()
