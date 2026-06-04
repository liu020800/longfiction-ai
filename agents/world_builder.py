import json
import logging
from core.llm_router import call_llm, TaskType
from core.models import WorldSetting

logger = logging.getLogger(__name__)

WORLD_SYSTEM = """你是一个世界观架构师，擅长构建网文世界设定。
你必须输出JSON格式，包含cultivation_system、factions、rules、history、locations。
确保体系严密、等级清晰、势力有利益冲突。"""

WORLD_PROMPT = """根据以下大纲，构建完整的世界观设定：

大纲：{outline}
类型：{genre}

请输出JSON：
{{
  "cultivation_system": "修炼/力量体系描述（含等级划分）",
  "factions": [{{"name": "势力名", "type": "类型", "description": "描述"}}],
  "rules": ["世界规则1", "世界规则2"],
  "history": ["重大历史事件1", "重大历史事件2"],
  "locations": [{{"name": "地名", "description": "描述"}}]
}}"""


class WorldBuilderAgent:
    async def build(self, outline: str, genre: str = "urban_fantasy") -> WorldSetting:
        prompt = WORLD_PROMPT.format(outline=outline, genre=genre)
        try:
            result = await call_llm(TaskType.WORLD, prompt, system=WORLD_SYSTEM, json_mode=True, temperature=0.7)
        except Exception as e:
            logger.warning(f"World building LLM call failed, using fallback: {e}")
            result = {}
        try:
            world = WorldSetting(**result)
        except Exception:
            if not isinstance(result, dict):
                result = {}
            world = WorldSetting(
                cultivation_system=self._as_text(result.get("cultivation_system", "")),
                factions=self._as_list(result.get("factions", [])),
                rules=self._as_list(result.get("rules", [])),
                history=self._as_list(result.get("history", [])),
                locations=self._as_list(result.get("locations", [])),
            )
        if not world.cultivation_system:
            world.cultivation_system = "成长型力量体系：角色通过关键事件、资源积累和心境突破逐步提升。"
        if not world.rules:
            world.rules = ["能力成长必须有代价", "势力关系变化必须有铺垫", "关键设定一旦出现不可随意推翻"]
        return world

    def _as_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _as_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return self._as_text(json.loads(text))
                except Exception:
                    return value
            return value
        if isinstance(value, dict):
            lines = []
            name = value.get("name") or value.get("title")
            description = value.get("description") or value.get("desc") or value.get("summary")
            if name:
                lines.append(f"体系名称：{name}")
            if description:
                lines.append(str(description))
            levels = value.get("levels") or value.get("ranks") or value.get("stages")
            if isinstance(levels, list) and levels:
                lines.append("等级划分：")
                for index, item in enumerate(levels, start=1):
                    if isinstance(item, dict):
                        rank = item.get("rank") or index
                        level_name = item.get("name") or item.get("title") or f"第{rank}级"
                        level_desc = item.get("description") or item.get("desc") or ""
                        lines.append(f"{rank}. {level_name}：{level_desc}")
                    else:
                        lines.append(f"{index}. {item}")
            handled = {"name", "title", "description", "desc", "summary", "levels", "ranks", "stages"}
            for key, item in value.items():
                if key in handled:
                    continue
                lines.append(f"{self._translate_key(key)}：{self._as_text(item)}")
            return "\n".join(line for line in lines if str(line).strip())
        if isinstance(value, list):
            return "\n".join(
                f"{index}. {self._as_text(item)}"
                for index, item in enumerate(value, start=1)
                if self._as_text(item)
            )
        return str(value)

    def _translate_key(self, key: str) -> str:
        mapping = {
            "principle": "运行原理",
            "cost": "代价",
            "limit": "限制",
            "limits": "限制",
            "source": "来源",
            "features": "特征",
            "abilities": "能力",
        }
        return mapping.get(str(key), str(key))

    async def expand_rules(self, world: WorldSetting) -> WorldSetting:
        prompt = f"""基于以下世界观，补充完善规则体系，输出JSON的rules数组：

当前修炼体系：{world.cultivation_system}
当前规则：{world.rules}
当前势力：{world.factions}

请输出补充的规则列表（JSON数组）。"""
        result = await call_llm(TaskType.WORLD, prompt, json_mode=True, temperature=0.5)
        try:
            if isinstance(result, list):
                world.rules.extend(result)
            elif isinstance(result, dict):
                world.rules.extend(result.get("rules", []))
        except Exception:
            pass
        return world
