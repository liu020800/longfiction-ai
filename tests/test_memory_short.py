"""记忆系统测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    print("=== 记忆系统测试 ===\n")

    from memory.working_memory import WorkingMemory
    from memory.relationship_graph import RelationshipGraph, RelationType

    print("[1] WorkingMemory - 基本操作")
    wm = WorkingMemory(capacity=5)
    wm.set("scene_location", "青云宗大殿", priority=9)
    wm.set("current_chars", ["林远", "张三"], priority=8)
    wm.set("mood", "紧张", priority=5)
    print(f"  Size: {len(wm)}")
    print(f"  Get scene_location: {wm.get('scene_location')}")
    print(f"  Has mood: {wm.has('mood')}")
    print(f"  To prompt: {wm.to_prompt()[:100]}")

    print("\n[2] WorkingMemory - 容量淘汰")
    wm2 = WorkingMemory(capacity=3)
    wm2.set("a", 1, priority=1)
    wm2.set("b", 2, priority=5)
    wm2.set("c", 3, priority=10)
    wm2.set("d", 4, priority=5)  # 应该淘汰 a
    print(f"  Has a (evicted): {wm2.has('a')}")
    print(f"  Has b: {wm2.has('b')}")
    print(f"  Has c: {wm2.has('c')}")
    print(f"  Has d: {wm2.has('d')}")

    print("\n[3] RelationshipGraph - 添加和查询")
    g = RelationshipGraph()
    g.add_relation("林远", "张三", RelationType.ENEMY, "宿敌", strength=8, chapter=1)
    g.add_relation("林远", "李师", RelationType.MENTOR, "师父", strength=9, chapter=1)
    g.add_relation("林远", "师妹", RelationType.FRIEND, "同门", strength=7, chapter=1)
    print(f"  Characters: {g.get_characters()}")
    print(f"  Relations of 林远: {len(g.get_relations_of('林远'))}")
    for rel in g.get_relations_of("林远"):
        other = rel.target if rel.source == "林远" else rel.source
        print(f"    -> {other} ({rel.relation_type.value}, strength={rel.strength})")

    print("\n[4] RelationshipGraph - 对立检测")
    print(f"  Lin+Zhang enemy vs Lin+Zhang friend (矛盾): {g.detect_contradiction('林远', '张三', RelationType.FRIEND)}")
    print(f"  Lin+Li mentor vs Lin+Li enemy (矛盾): {g.detect_contradiction('林远', '李师', RelationType.ENEMY)}")

    print("\n[5] RelationshipGraph - 文本输出")
    text = g.to_text()
    print(f"  Output preview: {text[:150]}...")

    print("\n=== Memory Tests OK ===")


if __name__ == "__main__":
    main()
