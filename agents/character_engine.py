import json
import logging
import re
from core.llm_router import call_llm, TaskType
from core.models import CharacterSheet

logger = logging.getLogger(__name__)

CHAR_SYSTEM = """你是一个人物设计专家，擅长创建有深度的网文角色。
你必须输出JSON数组，每个角色包含name、goal、personality、appearance、abilities、status。
确保：
- 每个角色有明确动机
- 性格多面不纸片化
- 人物间有利益冲突
- 有成长空间
- 如果大纲里已经给出角色姓名，必须优先复用这些姓名，严禁输出“主角/盟友/宿敌”这类占位符名称
- 不要把关系角色泛化成模板词，必须贴合悬疑故事语境"""

CHAR_PROMPT = """根据以下信息，设计主要角色：

大纲：{outline}
世界观：{world_summary}
类型：{genre}

已知角色名：{known_names}

请输出3-5个核心角色的JSON数组：
[
  {{
    "name": "角色名",
    "goal": "核心目标",
    "personality": ["性格1", "性格2"],
    "appearance": "外貌描述",
    "abilities": ["能力1"],
    "status": {{"level": "初始等级", "hp": 100}},
    "relationships": [],
    "memory": []
  }}
]"""

CHAR_UPDATE_PROMPT = """根据最新章节内容，更新以下角色状态：

角色：{name}
当前状态：{current_status}
当前性格：{personality}
当前目标：{goal}

新章节内容摘要：{chapter_summary}

请输出更新后的角色JSON：
{{
  "name": "{name}",
  "goal": "更新后的目标",
  "personality": ["性格"],
  "status": {{}},
  "memory": ["新增记忆"]
}}"""


class CharacterEngine:
    def _extract_candidate_names(self, outline: str) -> list[str]:
        text = outline or ""
        names: list[str] = []
        seen: set[str] = set()
        patterns = [
            r"\*\*([\u4e00-\u9fff]{2,4})[，,]",
            r"([\u4e00-\u9fff]{2,4})[，,]\s*\d{1,2}岁",
            r"([温苏陆林赵陈王李][\u4e00-\u9fff]{1,2})被发现在",
            r"([温苏陆林赵陈王李][\u4e00-\u9fff]{1,2})站在",
            r"([温苏陆林赵陈王李][\u4e00-\u9fff]{1,2})提出",
            r"##\s*【?主角设定】?.*?\*\*([\u4e00-\u9fff]{2,4})[，,]",
            r"与([\u4e00-\u9fff]{2,4})的关系",
        ]
        blocked = {
            "主角", "盟友", "宿敌", "警方", "死者", "凶手", "女人", "男人",
            "自己", "时间", "记忆", "实验", "清城", "现场", "公寓", "未来",
            "如果", "因为", "可以", "一个", "一种", "有一", "什么",
        }
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.S):
                name = match.strip()
                if name in blocked or len(name) < 2 or len(name) > 4:
                    continue
                if any(token in name for token in ["有一", "不是", "自己", "时间"]):
                    continue
                if name not in seen:
                    seen.add(name)
                    names.append(name)
        return names[:8]

    def _normalize_generated_characters(self, characters: list[CharacterSheet], outline: str) -> list[CharacterSheet]:
        candidate_names = self._extract_candidate_names(outline)
        if not characters:
            return characters
        generic_names = {"主角", "盟友", "宿敌", "反派", "配角", "警察", "死者"}
        assigned: set[str] = set()
        result: list[CharacterSheet] = []
        candidate_iter = [name for name in candidate_names if name not in assigned]
        for char in characters:
            if char.name in generic_names and candidate_iter:
                char.name = candidate_iter.pop(0)
            if char.name in assigned:
                suffix_base = char.name
                for fallback in candidate_names:
                    if fallback not in assigned:
                        char.name = fallback
                        break
                else:
                    idx = 2
                    while f"{suffix_base}{idx}" in assigned:
                        idx += 1
                    char.name = f"{suffix_base}{idx}"
            assigned.add(char.name)
            result.append(char)
        return result

    async def create_characters(self, outline: str, world_summary: str, genre: str = "urban_fantasy") -> list[CharacterSheet]:
        known_names = "、".join(self._extract_candidate_names(outline)) or "未显式给出"
        prompt = CHAR_PROMPT.format(outline=outline, world_summary=world_summary, genre=genre, known_names=known_names)
        try:
            result = await call_llm(TaskType.CHARACTER, prompt, system=CHAR_SYSTEM, json_mode=True, temperature=0.7)
        except Exception as e:
            logger.warning(f"Character creation LLM call failed, using fallback: {e}")
            result = []
        characters = []
        try:
            if isinstance(result, dict):
                result = result.get("characters", result.get("data", []))
            if isinstance(result, dict):
                result = [result]
            for c in result:
                if not isinstance(c, dict):
                    continue
                characters.append(CharacterSheet(**c))
        except Exception as e:
            logger.warning(f"Character creation failed: {e}")
        characters = self._normalize_generated_characters(characters, outline)
        if not characters:
            fallback_names = self._extract_candidate_names(outline)
            fallback_main = fallback_names[0] if len(fallback_names) > 0 else "苏漾"
            fallback_partner = fallback_names[1] if len(fallback_names) > 1 else "陆彦舟"
            fallback_third = fallback_names[2] if len(fallback_names) > 2 else "温静宜"
            characters = [
                CharacterSheet(
                    name=fallback_main,
                    goal="揭开案件真相，确认自己是否被卷入一场被设计的时间实验",
                    personality=["冷静", "警觉", "克制"],
                    appearance="清瘦、目光锐利，长期失眠带来轻微倦色",
                    abilities=["触觉残留共情"],
                    status={"level": "初始阶段", "role": "主调查者"},
                ),
                CharacterSheet(
                    name=fallback_partner,
                    goal="查清温静宜之死，判断苏漾究竟是嫌疑人、证人还是关键破局者",
                    personality=["敏锐", "理性", "强控制欲"],
                    appearance="衣着利落，目光锋利，常年保持高压工作状态",
                    abilities=["犯罪心理侧写", "刑侦审讯"],
                    status={"relationship": "对立中的合作对象"},
                ),
                CharacterSheet(
                    name=fallback_third,
                    goal="以自己的研究验证时间感知理论，并把关键结果藏在只有特定对象能读出的线索里",
                    personality=["克制", "偏执", "极端理性"],
                    appearance="学者气质浓，细节讲究，长期高压下显得苍白",
                    abilities=["神经时间感知研究", "实验设计"],
                    status={"relationship": "案件核心人物"},
                ),
            ]
        return characters

    async def update_character(self, char: CharacterSheet, chapter_summary: str) -> CharacterSheet:
        prompt = CHAR_UPDATE_PROMPT.format(
            name=char.name,
            current_status=char.status,
            personality=char.personality,
            goal=char.goal,
            chapter_summary=chapter_summary,
        )
        result = await call_llm(TaskType.CHARACTER, prompt, json_mode=True, temperature=0.5)
        try:
            char.goal = result.get("goal", char.goal)
            if result.get("personality"):
                char.personality = result["personality"]
            if result.get("status"):
                char.status.update(result["status"])
            if result.get("memory"):
                char.memory.extend(result["memory"])
                if len(char.memory) > 50:
                    char.memory = char.memory[-50:]
        except Exception:
            pass
        return char

    async def check_ooc(self, char: CharacterSheet, chapter_text: str) -> tuple[bool, str]:
        prompt = f"""检查以下章节中角色"{char.name}"是否OOC（性格崩坏）：

角色设定：性格{char.personality}，目标{char.goal}
章节内容：{chapter_text[:2000]}

请输出JSON：{{"is_ooc": true/false, "reason": "原因"}}"""
        result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
        try:
            return result.get("is_ooc", False), result.get("reason", "")
        except Exception:
            return False, ""
