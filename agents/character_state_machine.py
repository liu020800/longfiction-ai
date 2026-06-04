from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CharacterState(Enum):
    INITIAL = "initial"
    GROWING = "growing"
    STRONG = "strong"
    PEAK = "peak"
    DECLINING = "declining"
    RECOVERING = "recovering"


class RelationType(Enum):
    FRIEND = "friend"
    ENEMY = "enemy"
    NEUTRAL = "neutral"
    ALLY = "ally"
    RIVAL = "rival"
    MENTOR = "mentor"
    DISCIPLE = "disciple"


@dataclass
class StateTransition:
    from_state: CharacterState
    to_state: CharacterState
    trigger: str
    chapter_index: int
    description: str = ""


@dataclass
class CharacterStateMachine:
    name: str
    current_state: CharacterState = CharacterState.INITIAL
    power_level: int = 1
    max_power_level: int = 100
    history: List[StateTransition] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    last_updated_chapter: int = 0

    STATE_THRESHOLDS = {
        CharacterState.INITIAL: (1, 10),
        CharacterState.GROWING: (11, 40),
        CharacterState.STRONG: (41, 70),
        CharacterState.PEAK: (71, 90),
        CharacterState.DECLINING: (91, 95),
        CharacterState.RECOVERING: (96, 100),
    }

    def update_power(self, new_level: int, chapter_index: int, reason: str = "") -> bool:
        if new_level < 1:
            new_level = 1
        if new_level > self.max_power_level:
            new_level = self.max_power_level
        
        if new_level < self.power_level - 5 and chapter_index > self.last_updated_chapter:
            logger.warning(f"Power level regression for {self.name}: {self.power_level} -> {new_level}")
            return False
        
        old_level = self.power_level
        self.power_level = new_level
        self.last_updated_chapter = chapter_index
        
        new_state = self._get_state_for_level(new_level)
        if new_state != self.current_state:
            transition = StateTransition(
                from_state=self.current_state,
                to_state=new_state,
                trigger=f"power_change:{old_level}->{new_level}",
                chapter_index=chapter_index,
                description=reason
            )
            self.history.append(transition)
            self.current_state = new_state
            logger.info(f"Character {self.name} state changed: {transition.from_state.value} -> {transition.to_state.value}")
        
        return True

    def _get_state_for_level(self, level: int) -> CharacterState:
        for state, (low, high) in self.STATE_THRESHOLDS.items():
            if low <= level <= high:
                return state
        return CharacterState.INITIAL

    def can_perform_action(self, action_type: str) -> bool:
        action_requirements = {
            "major_battle": CharacterState.GROWING,
            "defeat_boss": CharacterState.STRONG,
            "change_world": CharacterState.PEAK,
        }
        required = action_requirements.get(action_type)
        if not required:
            return True
        
        state_order = list(CharacterState)
        return state_order.index(self.current_state) >= state_order.index(required)

    def get_progress_percentage(self) -> float:
        return (self.power_level / self.max_power_level) * 100

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "current_state": self.current_state.value,
            "power_level": self.power_level,
            "max_power_level": self.max_power_level,
            "progress": self.get_progress_percentage(),
            "last_updated_chapter": self.last_updated_chapter,
            "attributes": self.attributes,
            "history": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "trigger": t.trigger,
                    "chapter": t.chapter_index,
                    "description": t.description
                }
                for t in self.history[-10:]
            ]
        }


@dataclass
class Relationship:
    character1: str
    character2: str
    relation_type: RelationType
    strength: int = 50
    history: List[Dict] = field(default_factory=list)

    def update_relation(self, new_type: RelationType, delta: int = 0, chapter_index: int = 0, reason: str = ""):
        old_type = self.relation_type
        old_strength = self.strength
        
        self.relation_type = new_type
        self.strength = max(0, min(100, self.strength + delta))
        
        if old_type != new_type or delta != 0:
            self.history.append({
                "chapter": chapter_index,
                "from_type": old_type.value,
                "to_type": new_type.value,
                "strength_change": delta,
                "reason": reason
            })

    def to_dict(self) -> dict:
        return {
            "character1": self.character1,
            "character2": self.character2,
            "type": self.relation_type.value,
            "strength": self.strength,
            "history": self.history[-5:]
        }


class StateTransitionBlockError(Exception):
    def __init__(self, character_name: str, from_state: str, to_state: str, reason: str):
        self.character_name = character_name
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(f"角色「{character_name}」状态越级：{from_state} -> {to_state}，原因：{reason}")


ACTION_BEHAVIOR_MAP = {
    "major_battle": {
        "required_state": CharacterState.GROWING,
        "description": "参与重大战斗",
        "behavior_patterns": ["战斗", "对决", "交锋", "厮杀", "搏斗"],
    },
    "defeat_boss": {
        "required_state": CharacterState.STRONG,
        "description": "击败首领级敌人",
        "behavior_patterns": ["击败", "斩杀", "击杀boss", "消灭强敌"],
    },
    "change_world": {
        "required_state": CharacterState.PEAK,
        "description": "改变世界格局",
        "behavior_patterns": ["改变格局", "重塑秩序", "开创新时代", "颠覆势力"],
    },
    "teach_disciple": {
        "required_state": CharacterState.STRONG,
        "description": "收徒传授",
        "behavior_patterns": ["收徒", "传授", "教导", "指点"],
    },
    "found_faction": {
        "required_state": CharacterState.STRONG,
        "description": "创建势力",
        "behavior_patterns": ["创建势力", "创立势力", "组建势力", "建立组织", "建立势力", "开宗立派"],
    },
}

STATE_TRANSITION_RULES = {
    (CharacterState.INITIAL, CharacterState.GROWING): True,
    (CharacterState.GROWING, CharacterState.STRONG): True,
    (CharacterState.STRONG, CharacterState.PEAK): True,
    (CharacterState.PEAK, CharacterState.DECLINING): True,
    (CharacterState.DECLINING, CharacterState.RECOVERING): True,
    (CharacterState.RECOVERING, CharacterState.STRONG): True,
    (CharacterState.RECOVERING, CharacterState.PEAK): True,
}


class CharacterStateManager:
    def __init__(self):
        self.characters: Dict[str, CharacterStateMachine] = {}
        self.relationships: List[Relationship] = []
        self.dead_characters: set = set()

    def register_character(self, name: str, initial_power: int = 1, **attrs) -> CharacterStateMachine:
        machine = CharacterStateMachine(
            name=name,
            power_level=initial_power,
            attributes=attrs
        )
        self.characters[name] = machine
        return machine

    def get_character(self, name: str) -> Optional[CharacterStateMachine]:
        return self.characters.get(name)

    def mark_dead(self, name: str, chapter: int):
        self.dead_characters.add(name)
        if name in self.characters:
            machine = self.characters[name]
            machine.attributes["dead_chapter"] = chapter
            machine.attributes["is_dead"] = True

    def is_dead(self, name: str) -> bool:
        return name in self.dead_characters

    def update_character_power(self, name: str, new_level: int, chapter: int, reason: str = "") -> bool:
        char = self.get_character(name)
        if char:
            return char.update_power(new_level, chapter, reason)
        return False

    def validate_state_transition(self, name: str, target_state: CharacterState) -> List[str]:
        char = self.get_character(name)
        if not char:
            return []
        issues = []
        from_state = char.current_state
        if from_state == target_state:
            return []

        key = (from_state, target_state)
        if key not in STATE_TRANSITION_RULES:
            state_order = list(CharacterState)
            from_idx = state_order.index(from_state)
            to_idx = state_order.index(target_state)
            if to_idx > from_idx + 1 and target_state != CharacterState.RECOVERING:
                issues.append(
                    f"角色「{name}」状态越级：{from_state.value} -> {target_state.value}，"
                    f"需要经过中间状态"
                )

        if name in self.dead_characters and target_state != CharacterState.DECLINING:
            issues.append(f"角色「{name}」已死亡，不允许状态转移至{target_state.value}")

        return issues

    def block_invalid_transition(self, name: str, target_state: CharacterState):
        issues = self.validate_state_transition(name, target_state)
        if issues:
            char = self.get_character(name)
            raise StateTransitionBlockError(
                character_name=name,
                from_state=char.current_state.value if char else "unknown",
                to_state=target_state.value,
                reason=issues[0]
            )

    def validate_action_for_text(self, text: str, chapter_index: int) -> List[Dict]:
        violations = []
        for action_type, action_info in ACTION_BEHAVIOR_MAP.items():
            for pattern in action_info["behavior_patterns"]:
                if pattern in text:
                    required_state = action_info["required_state"]
                    state_order = list(CharacterState)
                    required_idx = state_order.index(required_state)

                    for name, machine in self.characters.items():
                        if name in text:
                            current_idx = state_order.index(machine.current_state)
                            if current_idx < required_idx:
                                violations.append({
                                    "character": name,
                                    "action": action_type,
                                    "action_desc": action_info["description"],
                                    "current_state": machine.current_state.value,
                                    "required_state": required_state.value,
                                    "chapter": chapter_index,
                                    "severity": "hard" if current_idx < required_idx - 1 else "soft",
                                })
                    break
        return violations

    def check_dead_character_in_text(self, text: str, chapter_index: int) -> List[Dict]:
        violations = []
        for name in self.dead_characters:
            if name in text:
                machine = self.characters.get(name)
                dead_ch = machine.attributes.get("dead_chapter", "?") if machine else "?"
                violations.append({
                    "character": name,
                    "issue": f"已死角色「{name}」（死于第{dead_ch}章）出现在第{chapter_index}章文本中",
                    "severity": "hard",
                })
        return violations

    def set_relationship(self, char1: str, char2: str, rel_type: RelationType, strength: int = 50):
        for rel in self.relationships:
            if (rel.character1 == char1 and rel.character2 == char2) or \
               (rel.character1 == char2 and rel.character2 == char1):
                rel.relation_type = rel_type
                rel.strength = strength
                return rel
        
        rel = Relationship(char1, char2, rel_type, strength)
        self.relationships.append(rel)
        return rel

    def get_relationships(self, char_name: str) -> List[Relationship]:
        return [
            rel for rel in self.relationships
            if rel.character1 == char_name or rel.character2 == char_name
        ]

    def validate_power_progression(self, chapter_history: Dict[int, Dict[str, int]]) -> List[str]:
        issues = []
        for name, machine in self.characters.items():
            levels = []
            for chapter in sorted(chapter_history.keys()):
                if name in chapter_history[chapter]:
                    levels.append((chapter, chapter_history[chapter][name]))
            
            for i in range(1, len(levels)):
                prev_ch, prev_level = levels[i-1]
                curr_ch, curr_level = levels[i]
                if curr_level < prev_level - 5:
                    issues.append(
                        f"Power regression for {name}: chapter {prev_ch}({prev_level}) -> chapter {curr_ch}({curr_level})"
                    )
        return issues

    def pre_generation_validate(self, chapter_index: int, plot_direction: str) -> List[str]:
        blocks = []
        action_violations = self.validate_action_for_text(plot_direction, chapter_index)
        for v in action_violations:
            blocks.append(
                f"WARN: 角色「{v['character']}」当前状态{v['current_state']}可能不足以执行{v['action_desc']}（建议达到{v['required_state']}）；生成时应写出铺垫或降低动作强度"
            )
        dead_violations = self.check_dead_character_in_text(plot_direction, chapter_index)
        for v in dead_violations:
            if v["severity"] == "hard":
                blocks.append(f"HARD: {v['issue']}")
        return blocks

    def to_dict(self) -> dict:
        return {
            "characters": {name: char.to_dict() for name, char in self.characters.items()},
            "relationships": [rel.to_dict() for rel in self.relationships],
            "dead_characters": list(self.dead_characters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CharacterStateManager':
        manager = cls()
        for name, char_data in data.get("characters", {}).items():
            machine = CharacterStateMachine(
                name=name,
                current_state=CharacterState(char_data.get("current_state", "initial")),
                power_level=char_data.get("power_level", 1),
                max_power_level=char_data.get("max_power_level", 100),
                last_updated_chapter=char_data.get("last_updated_chapter", 0),
                attributes=char_data.get("attributes", {})
            )
            manager.characters[name] = machine
        
        for rel_data in data.get("relationships", []):
            rel = Relationship(
                character1=rel_data["character1"],
                character2=rel_data["character2"],
                relation_type=RelationType(rel_data["type"]),
                strength=rel_data.get("strength", 50)
            )
            manager.relationships.append(rel)

        manager.dead_characters = set(data.get("dead_characters", []))
        
        return manager
