import json
import os
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    source: str
    target: str
    relation_type: str
    weight: float = 1.0
    description: str = ""
    established_chapter: int = 0
    last_updated_chapter: int = 0


class RelationshipGraph:
    def __init__(self, path: str = None):
        self.path = path
        self._adjacency: dict[str, list[Relationship]] = defaultdict(list)
        self._entities: set[str] = set()
        if path:
            self._load()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entity in data.get("entities", []):
                self._entities.add(entity)
            for edge in data.get("edges", []):
                rel = Relationship(**edge)
                self._adjacency[rel.source].append(rel)
                self._entities.add(rel.source)
                self._entities.add(rel.target)
        except Exception as e:
            logger.warning(f"Failed to load relationship graph: {e}")

    def save(self):
        if not self.path:
            return
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        edges = []
        for rels in self._adjacency.values():
            for rel in rels:
                edges.append(asdict(rel))
        data = {
            "entities": sorted(self._entities),
            "edges": edges,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_entity(self, name: str):
        self._entities.add(name)

    def add_relationship(self, source: str, target: str, relation_type: str, weight: float = 1.0, description: str = "", chapter: int = 0):
        self._entities.add(source)
        self._entities.add(target)

        for rel in self._adjacency[source]:
            if rel.target == target and rel.relation_type == relation_type:
                rel.weight = weight
                rel.description = description
                rel.last_updated_chapter = chapter
                self.save()
                return

        rel = Relationship(
            source=source,
            target=target,
            relation_type=relation_type,
            weight=weight,
            description=description,
            established_chapter=chapter,
            last_updated_chapter=chapter,
        )
        self._adjacency[source].append(rel)

        reverse = Relationship(
            source=target,
            target=source,
            relation_type=self._reverse_type(relation_type),
            weight=weight,
            description=description,
            established_chapter=chapter,
            last_updated_chapter=chapter,
        )
        self._adjacency[target].append(reverse)
        self.save()

    def _reverse_type(self, relation_type: str) -> str:
        reverse_map = {
            "师徒": "徒师",
            "徒师": "师徒",
            "父子": "子父",
            "子父": "父子",
            "母子": "子母",
            "子母": "母子",
            "敌对": "敌对",
            "盟友": "盟友",
            "友情": "友情",
            "恋人": "恋人",
            "仇敌": "仇敌",
            "上下级": "下上级",
            "下上级": "上下级",
            "兄弟": "兄弟",
            "姐妹": "姐妹",
        }
        return reverse_map.get(relation_type, relation_type)

    def get_relationships(self, entity: str) -> list[Relationship]:
        return list(self._adjacency.get(entity, []))

    def get_related_entities(self, entity: str) -> list[str]:
        return [rel.target for rel in self._adjacency.get(entity, [])]

    def get_relationship_between(self, source: str, target: str) -> list[Relationship]:
        return [rel for rel in self._adjacency.get(source, []) if rel.target == target]

    def get_entities_by_type(self, relation_type: str) -> list[tuple[str, str]]:
        pairs = []
        seen = set()
        for source, rels in self._adjacency.items():
            for rel in rels:
                key = tuple(sorted([rel.source, rel.target])) + (relation_type,)
                if rel.relation_type == relation_type and key not in seen:
                    pairs.append((rel.source, rel.target))
                    seen.add(key)
        return pairs

    def get_neighborhood(self, entity: str, depth: int = 2) -> dict[str, list[Relationship]]:
        result = {}
        visited = set()
        queue = [(entity, 0)]

        while queue:
            current, d = queue.pop(0)
            if current in visited or d > depth:
                continue
            visited.add(current)
            rels = self.get_relationships(current)
            if rels:
                result[current] = rels
            if d < depth:
                for rel in rels:
                    if rel.target not in visited:
                        queue.append((rel.target, d + 1))

        return result

    def get_context_text(self, entity: str = None) -> str:
        if entity:
            rels = self.get_relationships(entity)
            if not rels:
                return ""
            lines = [f"【{entity}的关系网络】"]
            for rel in rels:
                lines.append(f"  → {rel.target} ({rel.relation_type}, 强度:{rel.weight:.1f}): {rel.description}")
            return "\n".join(lines)

        lines = ["【角色关系网络】"]
        seen = set()
        for source, rels in self._adjacency.items():
            for rel in rels:
                key = tuple(sorted([rel.source, rel.target])) + (rel.relation_type,)
                if key not in seen:
                    lines.append(f"  {rel.source} ↔ {rel.target}: {rel.relation_type} ({rel.description})")
                    seen.add(key)
        return "\n".join(lines) if len(lines) > 1 else ""

    def sync_from_characters(self, characters: dict, chapter: int = 0):
        for name, char in characters.items():
            self.add_entity(name)
            for rel_data in (char.relationships or []):
                target = rel_data.get("name", rel_data.get("target", ""))
                rel_type = rel_data.get("relation", rel_data.get("type", "相关"))
                desc = rel_data.get("description", rel_data.get("desc", ""))
                if target:
                    self.add_relationship(
                        source=name,
                        target=target,
                        relation_type=rel_type,
                        description=desc,
                        chapter=chapter,
                    )
        # Always save, even if only entities were added (no edges)
        self.save()

    def extract_relationships_from_content(self, content: str, character_names: list[str], chapter: int = 0):
        """Extract character relationships from chapter text using co-occurrence and keyword patterns."""
        if not character_names or not content:
            return

        import re

        # Relationship indicator patterns
        RELATION_PATTERNS = [
            (r"({A}).*?(?:是|为).*?({B}).*?(?:师傅|师父|老师|导师)", "师徒"),
            (r"({A}).*?(?:是|为).*?({B}).*?(?:徒弟|弟子|学生)", "师徒"),
            (r"({A}).*?(?:和|与|跟).*?({B}).*?(?:对抗|敌对|为敌|交战|冲突)", "敌对"),
            (r"({A}).*?(?:和|与|跟).*?({B}).*?(?:结盟|联手|合作|并肩)", "盟友"),
            (r"({A}).*?(?:和|与|跟).*?({B}).*?(?:是.*?朋友|友情|友谊)", "友情"),
            (r"({A}).*?(?:和|与|跟).*?({B}).*?(?:相爱|恋人|情侣|爱意|暗恋)", "恋人"),
            (r"({A}).*?(?:是|为).*?({B}).*?(?:父亲|爸爸|爹)", "父子"),
            (r"({A}).*?(?:是|为).*?({B}).*?(?:母亲|妈妈|娘)", "母子"),
            (r"({A}).*?(?:是|为).*?({B}).*?(?:兄弟|哥哥|弟弟)", "兄弟"),
            (r"({A}).*?(?:是|为).*?({B}).*?(?:姐妹|姐姐|妹妹)", "姐妹"),
            (r"({A}).*?(?:和|与|跟).*?({B}).*?(?:仇恨|仇敌|杀.*?之仇)", "仇敌"),
        ]

        # Co-occurrence analysis: find characters appearing in the same sentence/paragraph
        paragraphs = content.split("\n")
        cooccurrence: dict[tuple[str, str], int] = {}
        for para in paragraphs:
            present = [name for name in character_names if name in para]
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    pair = tuple(sorted([present[i], present[j]]))
                    cooccurrence[pair] = cooccurrence.get(pair, 0) + 1

        # Check specific relationship patterns
        found_specific = set()
        for a_name in character_names:
            for b_name in character_names:
                if a_name == b_name:
                    continue
                for pattern_template, rel_type in RELATION_PATTERNS:
                    pattern = pattern_template.replace("{A}", re.escape(a_name)).replace("{B}", re.escape(b_name))
                    if re.search(pattern, content):
                        pair_key = tuple(sorted([a_name, b_name])) + (rel_type,)
                        if pair_key not in found_specific:
                            found_specific.add(pair_key)
                            self.add_relationship(
                                source=a_name,
                                target=b_name,
                                relation_type=rel_type,
                                description=f"第{chapter+1}章中发现",
                                chapter=chapter,
                            )

        # For frequently co-occurring characters without specific relationship, add "相关"
        for (a, b), count in cooccurrence.items():
            if count >= 2:  # At least 2 co-occurrences
                pair_key = tuple(sorted([a, b]))
                # Check if we already found a specific relationship
                has_specific = any(
                    tuple(sorted([a, b])) == (pk[0], pk[1])
                    for pk in found_specific
                )
                if not has_specific:
                    existing = self.get_relationship_between(a, b)
                    if not existing:
                        self.add_relationship(
                            source=a,
                            target=b,
                            relation_type="相关",
                            weight=min(count * 0.3, 1.0),
                            description=f"第{chapter+1}章中多次同场出现({count}次)",
                            chapter=chapter,
                        )

        self.save()
        logger.info(f"Relationship extraction: {len(found_specific)} specific + {sum(1 for c in cooccurrence.values() if c >= 2)} co-occurrence pairs")

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def edge_count(self) -> int:
        seen = set()
        count = 0
        for source, rels in self._adjacency.items():
            for rel in rels:
                key = tuple(sorted([rel.source, rel.target])) + (rel.relation_type,)
                if key not in seen:
                    seen.add(key)
                    count += 1
        return count

    def clear(self):
        self._adjacency.clear()
        self._entities.clear()
        if self.path and os.path.exists(self.path):
            os.remove(self.path)
