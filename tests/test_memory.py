"""测试 memory 模块：工作记忆、关系图谱。"""
import pytest

from memory.working_memory import WorkingMemory
from memory.relationship_graph import RelationshipGraph, RelationType


class TestWorkingMemory:
    def test_basic_set_get(self):
        wm = WorkingMemory(capacity=5)
        wm.set("key1", "value1")
        assert wm.get("key1") == "value1"

    def test_miss(self):
        wm = WorkingMemory()
        assert wm.get("nonexistent") is None

    def test_capacity_eviction(self):
        wm = WorkingMemory(capacity=3)
        wm.set("a", 1, priority=1)  # 最低优先级
        wm.set("b", 2, priority=5)
        wm.set("c", 3, priority=5)
        wm.set("d", 4, priority=5)  # 应该淘汰 a
        assert wm.get("a") is None
        assert wm.get("b") == 2

    def test_priority_override(self):
        wm = WorkingMemory(capacity=2)
        wm.set("a", 1, priority=5)
        wm.set("b", 2, priority=10)
        wm.set("c", 3, priority=1)  # 淘汰 a（最低优先级）
        assert wm.get("a") is None
        assert wm.get("b") == 2
        assert wm.get("c") == 3

    def test_update_existing(self):
        wm = WorkingMemory()
        wm.set("k", "v1")
        wm.set("k", "v2")
        assert wm.get("k") == "v2"
        assert len(wm) == 1

    def test_to_prompt(self):
        wm = WorkingMemory()
        wm.set("scene", "青云宗大殿", priority=8)
        wm.set("character", "林远", priority=9)
        text = wm.to_prompt()
        assert "青云宗大殿" in text
        assert "林远" in text

    def test_clear(self):
        wm = WorkingMemory()
        wm.set("a", 1)
        wm.clear()
        assert len(wm) == 0


class TestRelationshipGraph:
    def test_add_relation(self):
        g = RelationshipGraph()
        g.add_relation("林远", "张三", RelationType.ENEMY, "宿敌", strength=8, chapter=1)
        rel = g.get_relation("林远", "张三")
        assert rel is not None
        assert rel.relation_type == RelationType.ENEMY
        assert rel.strength == 8

    def test_symmetric_lookup(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        # 不管 A->B 还是 B->A 都应该查到
        assert g.get_relation("A", "B") is not None
        assert g.get_relation("B", "A") is not None

    def test_get_relations_of(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        g.add_relation("A", "C", RelationType.ENEMY)
        g.add_relation("B", "C", RelationType.NEUTRAL)
        a_rels = g.get_relations_of("A")
        assert len(a_rels) == 2

    def test_get_by_type(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        g.add_relation("C", "D", RelationType.FRIEND)
        g.add_relation("E", "F", RelationType.ENEMY)
        friends = g.get_by_type(RelationType.FRIEND)
        assert len(friends) == 2

    def test_strong_relations(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND, strength=8)
        g.add_relation("C", "D", RelationType.FRIEND, strength=5)
        strong = g.get_strong_relations(threshold=7)
        assert len(strong) == 1
        assert strong[0].strength == 8

    def test_contradiction_detection(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        # 期望是敌人，矛盾
        assert g.detect_contradiction("A", "B", RelationType.ENEMY)
        # 期望还是朋友，不矛盾
        assert not g.detect_contradiction("A", "B", RelationType.FRIEND)

    def test_to_text(self):
        g = RelationshipGraph()
        g.add_relation("林远", "张三", RelationType.ENEMY, "宿敌", strength=8, chapter=1)
        text = g.to_text()
        assert "林远" in text
        assert "张三" in text
        assert "敌人" in text or "enemy" in text.lower()

    def test_get_characters(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        g.add_relation("B", "C", RelationType.ENEMY)
        chars = g.get_characters()
        assert set(chars) == {"A", "B", "C"}

    def test_clear(self):
        g = RelationshipGraph()
        g.add_relation("A", "B", RelationType.FRIEND)
        g.clear()
        assert g.get_relation("A", "B") is None
