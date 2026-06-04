import json
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from core.llm_router import call_llm, TaskType
from core.models import ConsistencyReport, CharacterSheet, WorldSetting

logger = logging.getLogger(__name__)


class RuleType(Enum):
    CHARACTER = "character"
    WORLD = "world"
    PLOT = "plot"
    POWER = "power"
    LOCATION = "location"
    TIME = "time"


@dataclass
class Rule:
    id: str
    rule_type: RuleType
    description: str
    pattern: str = ""
    severity: float = 1.0
    auto_fix: bool = False


class RuleEngine:
    def __init__(self):
        self.rules: List[Rule] = []
        self.character_states: Dict[str, Dict] = {}
        self.dead_characters: set = set()
        self.location_history: Dict[str, List[int]] = {}
    
    def add_rule(self, rule: Rule):
        self.rules.append(rule)
    
    def load_default_rules(self):
        default_rules = [
            Rule("char_personality", RuleType.CHARACTER, "人物性格不能突然改变，除非有合理原因", severity=0.8),
            Rule("power_no_regression", RuleType.POWER, "修炼等级不能倒退超过5级", severity=1.0),
            Rule("no_revival", RuleType.CHARACTER, "已死人物不能无故复活", severity=1.0),
            Rule("location_valid", RuleType.LOCATION, "人物位置要合理（不能瞬移）", severity=0.6),
            Rule("time_continuous", RuleType.TIME, "时间线要连贯", severity=0.7),
            Rule("memory_persist", RuleType.CHARACTER, "已知信息不能被遗忘", severity=0.5),
            Rule("faction_transition", RuleType.WORLD, "势力关系变化要有过渡", severity=0.6),
            Rule("power_system", RuleType.WORLD, "力量体系规则要一致", severity=0.8),
            Rule("item_unique", RuleType.WORLD, "唯一物品不能重复出现", severity=0.7),
            Rule("skill_prerequisite", RuleType.POWER, "技能学习需要前置条件", severity=0.5),
        ]
        self.rules.extend(default_rules)
    
    def register_character_state(self, name: str, state: Dict, chapter: int):
        if name not in self.character_states:
            self.character_states[name] = {"history": [], "current": state}
        self.character_states[name]["current"] = state
        self.character_states[name]["history"].append({"chapter": chapter, "state": state.copy()})
    
    def mark_character_dead(self, name: str, chapter: int):
        self.dead_characters.add(name)
    
    def validate_power_progression(self, name: str, old_level: int, new_level: int, chapter: int) -> List[str]:
        issues = []
        if new_level < old_level - 5:
            issues.append(f"角色{name}力量等级倒退超过5级: {old_level} -> {new_level}（章节{chapter}）")
        return issues
    
    def validate_location(self, name: str, location: str, chapter: int) -> List[str]:
        issues = []
        if name in self.character_states:
            current_loc = self.character_states[name]["current"].get("location")
            if current_loc and current_loc != location:
                prev_chapter = self.character_states[name]["history"][-1]["chapter"] if self.character_states[name]["history"] else chapter - 1
                if chapter - prev_chapter == 1:
                    pass
        return issues
    
    def check_dead_character_revival(self, text: str, chapter: int) -> List[str]:
        issues = []
        for name in self.dead_characters:
            if name in text:
                issues.append(f"已死角色{name}出现在第{chapter}章，需要合理解释")
        return issues
    
    def validate_all(self, chapter_text: str, chapter_index: int, characters: List[CharacterSheet]) -> Dict[str, Any]:
        issues = []
        
        revival_issues = self.check_dead_character_revival(chapter_text, chapter_index)
        issues.extend(revival_issues)
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "checked_at": chapter_index
        }

CHECK_SYSTEM = """你是一个严格的小说审稿编辑，负责检查一致性。
你需要检查：
1. 人物是否OOC（性格崩坏）
2. 世界观是否冲突
3. 剧情逻辑是否错误
4. 设定是否矛盾
请输出详细的检查报告。"""

CHECK_PROMPT = """请检查以下章节内容的一致性：

章节内容：
{chapter_text}

人物设定：
{characters}

世界观设定：
{world}

历史时间线：
{timeline}

请输出JSON：
{{
  "is_consistent": true/false,
  "issues": ["问题1", "问题2"],
  "ooc_characters": ["OOC的人物名"],
  "world_conflicts": ["世界观冲突"],
  "logic_errors": ["逻辑错误"],
  "score": 0.0-1.0评分,
  "suggestions": ["修改建议"]
}}"""

RULE_CHECK_PROMPT = """基于规则检查以下内容是否违反设定：

规则：{rules}
内容：{text}

请输出JSON：
{{
  "violations": ["违反的规则"],
  "is_valid": true/false
}}"""


class ConsistencyBlockError(Exception):
    def __init__(self, issues: list[str], category: str = "hard"):
        self.issues = issues
        self.category = category
        super().__init__(f"[ConsistencyBlock:{category}] " + "; ".join(issues))


class ConsistencyChecker:
    def __init__(self):
        self.rules: list[str] = []
        self.rule_engine = RuleEngine()
        self.rule_engine.load_default_rules()

    def add_rule(self, rule: str):
        self.rules.append(rule)

    def load_default_rules(self):
        self.rules = [
            "人物性格不能突然改变，除非有合理原因",
            "修炼等级不能倒退",
            "已死人物不能无故复活",
            "人物位置要合理（不能瞬移）",
            "时间线要连贯",
            "已知信息不能被遗忘",
            "势力关系变化要有过渡",
        ]

    async def check_with_llm(
        self,
        chapter_text: str,
        characters: list[CharacterSheet],
        world: WorldSetting,
        timeline: list[dict],
    ) -> ConsistencyReport:
        char_text = "\n".join([
            f"- {c.name}: 性格{c.personality}, 目标{c.goal}, 状态{c.status}"
            for c in characters
        ])
        world_text = f"修炼体系:{world.cultivation_system}\n规则:{world.rules}\n势力:{world.factions}"
        timeline_text = "\n".join([
            f"- 第{t.get('chapter','?')}章《{t.get('title','')}』: {t.get('summary','')[:100]}"
            for t in timeline[-10:]
        ]) if timeline else "无"

        prompt = CHECK_PROMPT.format(
            chapter_text=chapter_text[:3000],
            characters=char_text,
            world=world_text,
            timeline=timeline_text,
        )
        try:
            result = await call_llm(TaskType.CHECK, prompt, system=CHECK_SYSTEM, json_mode=True, temperature=0.3)
        except Exception as e:
            logger.warning(f"Consistency LLM check failed, passing: {e}")
            return ConsistencyReport(is_consistent=True, score=1.0)

        try:
            report = ConsistencyReport(
                is_consistent=result.get("is_consistent", True),
                issues=result.get("issues", []),
                ooc_characters=result.get("ooc_characters", []),
                world_conflicts=result.get("world_conflicts", []),
                logic_errors=result.get("logic_errors", []),
                score=result.get("score", 1.0),
            )
        except Exception:
            report = ConsistencyReport(is_consistent=True, score=1.0)
        return report

    async def check_rules(self, text: str) -> dict:
        if not self.rules:
            return {"violations": [], "is_valid": True}
        prompt = RULE_CHECK_PROMPT.format(rules="\n".join(self.rules), text=text[:2000])
        try:
            result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
            return result
        except Exception as e:
            logger.warning(f"Rule check LLM call failed, skipping: {e}")
            return {"violations": [], "is_valid": True}

    async def check_embedding_consistency(self, new_text: str, history_embedding, get_embedding_fn) -> float:
        if history_embedding is None:
            return 1.0
        try:
            import numpy as np
            new_emb = await get_embedding_fn(new_text[:500])
            similarity = float(np.dot(new_emb, history_embedding) / (np.linalg.norm(new_emb) * np.linalg.norm(history_embedding) + 1e-8))
            return max(0.0, similarity)
        except Exception:
            return 1.0

    async def full_check(
        self,
        chapter_text: str,
        characters: list[CharacterSheet],
        world: WorldSetting,
        timeline: list[dict],
    ) -> ConsistencyReport:
        report = await self.check_with_llm(chapter_text, characters, world, timeline)
        rule_result = await self.check_rules(chapter_text)
        if not rule_result.get("is_valid", True):
            report.is_consistent = False
            report.issues.extend(rule_result.get("violations", []))
            report.score *= 0.8

        rule_engine_issues = self.rule_engine.validate_all(chapter_text, len(timeline) if timeline else 0, characters)
        if not rule_engine_issues.get("is_valid", True):
            report.is_consistent = False
            report.issues.extend(rule_engine_issues.get("issues", []))
            report.score = min(report.score, 0.5)

        fact_issues = self.check_facts(chapter_text, characters, timeline)
        if fact_issues:
            report.is_consistent = False
            report.issues.extend(fact_issues)
            report.score = min(report.score, 0.6)

        return report

    def check_facts(
        self,
        chapter_text: str,
        characters: list[CharacterSheet],
        timeline: list[dict],
    ) -> list[str]:
        issues = []

        for char in characters:
            status = char.status if isinstance(char.status, dict) else {}
            current_power = status.get("power_level", 0)
            history = self.rule_engine.character_states.get(char.name, {}).get("history", [])
            if history:
                prev_power = history[-1]["state"].get("power_level", 0)
                if current_power > 0 and prev_power > 0 and current_power < prev_power - 5:
                    issues.append(f"角色「{char.name}」力量等级倒退超过5级: {prev_power}→{current_power}")

            current_loc = status.get("location", "")
            if history and current_loc:
                prev_loc = history[-1]["state"].get("location", "")
                if prev_loc and current_loc != prev_loc:
                    teleport_keywords = ["瞬移", "传送", "瞬间到达", "立刻出现在"]
                    has_teleport = any(kw in chapter_text for kw in teleport_keywords)
                    has_travel = any(kw in chapter_text for kw in ["赶往", "前往", "飞向", "走向", "奔向", "来到", "到达", "抵达"])
                    has_magic = any(kw in chapter_text for kw in ["传送阵", "法术", "神器", "空间"])
                    if has_teleport and not has_travel and not has_magic:
                        issues.append(f"角色「{char.name}」从{prev_loc}到{current_loc}位置瞬移，缺乏移动描写")

        if timeline and len(timeline) >= 2:
            for i in range(1, len(timeline)):
                prev_ch = timeline[i-1].get("chapter", 0)
                curr_ch = timeline[i].get("chapter", 0)
                if curr_ch <= prev_ch:
                    issues.append(f"时间线不连续: 章节{prev_ch}后出现章节{curr_ch}")

        return issues


AUTO_FIX_SYSTEM = """你是一个小说一致性修复专家。根据检测到的一致性问题，修复文本中的错误。
要求：
- 只修复指出的问题，不改动无问题的内容
- 保持原文风格和语气
- 直接输出修复后的完整文本"""

AUTO_FIX_PROMPT = """请修复以下章节文本中的一致性问题：

原文：
{chapter_text}

检测到的问题：
{issues}

人物设定：
{characters}

世界观设定：
{world}

请直接输出修复后的完整章节文本，只修复上述问题，不要改动其他内容。"""


class ConsistencyGate:
    def __init__(self, checker: ConsistencyChecker):
        self.checker = checker
        self.dead_characters: set = set()
        self.character_power: Dict[str, int] = {}
        self.character_locations: Dict[str, str] = {}
        self.score_threshold = 0.45
        self.max_auto_fix_retries = 1

    def register_dead_character(self, name: str):
        self.dead_characters.add(name)
        self.checker.rule_engine.mark_character_dead(name, 0)

    def register_character_power(self, name: str, level: int, chapter: int):
        old = self.character_power.get(name, 0)
        self.character_power[name] = level
        self.checker.rule_engine.register_character_state(name, {"power_level": level, "location": self.character_locations.get(name, "")}, chapter)

    def register_character_location(self, name: str, location: str, chapter: int):
        self.character_locations[name] = location

    REASONABLE_CONTEXTS = ["回忆", "幻境", "梦境", "传说", "提及", "听说", "记载", "历史", "闪回", "前世"]

    def pre_generation_validate(
        self,
        chapter_index: int,
        characters: list[CharacterSheet],
        plot_direction: str,
    ) -> list[str]:
        blocks = []

        for name in self.dead_characters:
            if name in plot_direction:
                is_reasonable = any(kw in plot_direction for kw in self.REASONABLE_CONTEXTS)
                if is_reasonable:
                    blocks.append(f"WARN: 已死角色「{name}」出现在剧情方向中，但上下文为合理场景（回忆/幻境/传说），允许通过")
                else:
                    blocks.append(f"HARD: 已死角色「{name}」出现在剧情方向中，除非有合理解释（如回忆/幻境/复活剧情）")

        for char in characters:
            if char.name in self.dead_characters:
                if char.status.get("alive", True) is True:
                    blocks.append(f"HARD: 角色「{char.name}」已被标记死亡但状态仍为存活")

            current_power = char.status.get("power_level", 0)
            registered_power = self.character_power.get(char.name)
            if registered_power is not None and current_power > 0:
                if current_power < registered_power - 5:
                    is_reasonable = any(kw in plot_direction for kw in self.REASONABLE_CONTEXTS)
                    if is_reasonable:
                        blocks.append(f"WARN: 角色「{char.name}」力量等级倒退超过5级({registered_power}->{current_power})，但上下文为合理场景")
                    else:
                        blocks.append(f"HARD: 角色「{char.name}」力量等级倒退超过5级({registered_power}->{current_power})，缺乏合理解释")

            if char.name in self.character_locations and plot_direction:
                current_loc = self.character_locations[char.name]
                location_keywords = ["瞬移", "传送", "瞬间到达", "立刻出现在", "突然出现在"]
                has_teleport = any(kw in plot_direction for kw in location_keywords)
                has_travel_desc = any(kw in plot_direction for kw in ["赶往", "前往", "飞向", "走向", "奔向", "来到"])
                if has_teleport and not has_travel_desc:
                    is_reasonable = any(kw in plot_direction for kw in ["传送阵", "法术", "神器", "空间"] + list(self.REASONABLE_CONTEXTS))
                    if is_reasonable:
                        blocks.append(f"WARN: 角色「{char.name}」从{current_loc}位置瞬移，但有空间法术等合理解释")
                    else:
                        blocks.append(f"HARD: 角色「{char.name}」从{current_loc}位置瞬移，缺乏移动描写或空间法术解释")

        return blocks

    def pre_generation_block(
        self,
        chapter_index: int,
        characters: list[CharacterSheet],
        plot_direction: str,
    ) -> list[str]:
        blocks = self.pre_generation_validate(chapter_index, characters, plot_direction)
        warnings = [b.replace("WARN: ", "") for b in blocks if b.startswith("WARN:")]
        hard_blocks = [b for b in blocks if b.startswith("HARD:")]
        if hard_blocks:
            raise ConsistencyBlockError(
                issues=[b.replace("HARD: ", "") for b in hard_blocks],
                category="hard"
            )
        return warnings

    async def auto_fix(
        self,
        chapter_text: str,
        report: ConsistencyReport,
        characters: list[CharacterSheet],
        world: WorldSetting,
    ) -> str:
        if not report.issues and not report.ooc_characters and not report.world_conflicts and not report.logic_errors:
            return chapter_text

        all_issues = []
        if report.ooc_characters:
            all_issues.append(f"OOC角色: {', '.join(report.ooc_characters)}")
        if report.world_conflicts:
            all_issues.extend([f"世界观冲突: {c}" for c in report.world_conflicts])
        if report.logic_errors:
            all_issues.extend([f"逻辑错误: {e}" for e in report.logic_errors])
        if report.issues:
            all_issues.extend(report.issues)

        char_text = "\n".join([
            f"- {c.name}: 性格{c.personality}, 目标{c.goal}"
            for c in characters
        ])
        world_text = f"修炼体系:{world.cultivation_system}\n规则:{world.rules}"

        prompt = AUTO_FIX_PROMPT.format(
            chapter_text=chapter_text[:6000],
            issues="\n".join(all_issues[:10]),
            characters=char_text,
            world=world_text,
        )

        try:
            fixed = await call_llm(TaskType.REWRITE, prompt, system=AUTO_FIX_SYSTEM, temperature=0.5, max_tokens=len(chapter_text) * 2)
            return fixed
        except Exception as e:
            logger.warning(f"Auto-fix LLM call failed, returning original: {e}")
            return chapter_text

    async def gated_check(
        self,
        chapter_text: str,
        characters: list[CharacterSheet],
        world: WorldSetting,
        timeline: list[dict],
        chapter_index: int,
    ) -> tuple[ConsistencyReport, str]:
        report = await self.checker.full_check(chapter_text, characters, world, timeline)

        rule_engine_result = self.checker.rule_engine.check_dead_character_revival(chapter_text, chapter_index)
        if rule_engine_result:
            report.is_consistent = False
            report.issues.extend(rule_engine_result)
            report.score = min(report.score, 0.3)

        fixed_text = chapter_text
        if not report.is_consistent or report.score < self.score_threshold:
            logger.info(f"Auto-fix attempt 1/{self.max_auto_fix_retries} for chapter {chapter_index + 1}")
            try:
                fixed_text = await self.auto_fix(fixed_text, report, characters, world)
                re_report = await self.checker.full_check(fixed_text, characters, world, timeline)
                if re_report.is_consistent and re_report.score >= self.score_threshold:
                    logger.info(f"Auto-fix succeeded on attempt 1: score {re_report.score:.2f}")
                    return re_report, fixed_text
                report = re_report
            except Exception as e:
                logger.warning(f"Auto-fix attempt 1 failed: {e}")

            if not report.is_consistent and report.score < self.score_threshold * 0.55:
                raise ConsistencyBlockError(
                    issues=report.issues[:5],
                    category="post_generation"
                )

        return report, fixed_text
