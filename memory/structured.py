import json
import os
import logging
from typing import Optional
from core.config import settings
from core.models import CharacterSheet, WorldSetting

logger = logging.getLogger(__name__)


class StructuredMemory:
    def __init__(self, path: str = None):
        self.path = path or settings.MEMORY_STRUCT_PATH
        self.characters: dict[str, CharacterSheet] = {}
        self.world: WorldSetting = WorldSetting()
        self.timeline: list[dict] = []
        self.plot_arcs: list[dict] = []
        self.chapter_summaries: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, cdata in data.get("characters", {}).items():
                    self.characters[name] = CharacterSheet(**cdata)
                if data.get("world"):
                    self.world = WorldSetting(**data["world"])
                self.timeline = data.get("timeline", [])
                self.plot_arcs = data.get("plot_arcs", [])
                self.chapter_summaries = data.get("chapter_summaries", [])
            except Exception as e:
                logger.warning(f"Failed to load structured memory: {e}")

    def save(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = {
            "characters": {n: c.model_dump() for n, c in self.characters.items()},
            "world": self.world.model_dump(),
            "timeline": self.timeline,
            "plot_arcs": self.plot_arcs,
            "chapter_summaries": self.chapter_summaries,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_character(self, char: CharacterSheet):
        self.characters[char.name] = char
        self.save()

    def get_character(self, name: str) -> Optional[CharacterSheet]:
        return self.characters.get(name)

    def update_world(self, world: WorldSetting):
        self.world = world
        self.save()

    def add_timeline_event(self, event: dict):
        self.timeline.append(event)
        self.save()

    def add_chapter_summary(self, chapter_idx: int, title: str, summary: str):
        self.chapter_summaries.append({
            "chapter": chapter_idx,
            "title": title,
            "summary": summary,
        })
        self.save()

    def upsert_chapter_summary(self, chapter_idx: int, title: str, summary: str, observations: dict | None = None):
        payload = {
            "chapter": chapter_idx,
            "title": title,
            "summary": summary,
            "observations": observations or {},
        }
        replaced = False
        for idx, item in enumerate(self.chapter_summaries):
            if int(item.get("chapter", -1)) == chapter_idx:
                self.chapter_summaries[idx] = payload
                replaced = True
                break
        if not replaced:
            self.chapter_summaries.append(payload)
        self.chapter_summaries.sort(key=lambda item: int(item.get("chapter", -1)))
        self.save()

    def add_plot_arc(self, arc: dict):
        self.plot_arcs.append(arc)
        self.save()

    def clear_story_state(self):
        self.timeline = []
        self.plot_arcs = []
        self.chapter_summaries = []
        self.save()

    def get_chapter_summary(self, chapter_idx: int) -> str:
        """获取指定章节的摘要文本。"""
        for cs in self.chapter_summaries:
            if int(cs.get("chapter", -1)) == chapter_idx:
                return cs.get("summary", "")
        return ""

    def get_chapter_observations(self, chapter_idx: int) -> dict:
        """获取指定章节的观察数据（角色在场、情绪、钩子等）。"""
        for cs in self.chapter_summaries:
            if int(cs.get("chapter", -1)) == chapter_idx:
                return cs.get("observations", {})
        return {}

    def get_all_character_names(self) -> list[str]:
        return list(self.characters.keys())

    def get_character_profiles_text(self) -> str:
        lines = []
        for name, char in self.characters.items():
            voice = char.voice or {}
            voice_hint = ""
            if voice:
                parts = []
                if voice.get("style_hint"):
                    parts.append(str(voice.get("style_hint")))
                if voice.get("characteristic_phrases"):
                    parts.append(f"习惯词:{'、'.join(list(voice.get('characteristic_phrases', []) or [])[:4])}")
                voice_hint = f" 说话风格:{'；'.join(parts[:2])}" if parts else ""
            lines.append(f"【{name}】目标:{char.goal} 性格:{','.join(char.personality)} 状态:{char.status}{voice_hint}")
        return "\n".join(lines)

    def get_world_text(self) -> str:
        w = self.world
        parts = []
        if w.cultivation_system:
            parts.append(f"修炼体系:{w.cultivation_system}")
        if w.factions:
            parts.append(f"势力:{w.factions}")
        if w.rules:
            parts.append(f"规则:{w.rules}")
        if w.history:
            history_text = "；".join(str(h)[:60] for h in w.history[:5])
            parts.append(f"历史背景（仅供参考，勿主动引入正文）:{history_text}")
        return "\n".join(parts)

    def get_unresolved_foreshadowing(self) -> list[dict]:
        """获取未回收的伏笔列表"""
        try:
            from core.database import SessionLocal
            from models.db_service import ForeshadowingService
            if self.path and "sessions" in self.path:
                # 从 path 中提取 session_id
                parts = self.path.split(os.sep)
                if "sessions" in parts:
                    idx = parts.index("sessions")
                    if idx + 1 < len(parts):
                        project_id = parts[idx + 1]
                        with SessionLocal() as db:
                            fs = ForeshadowingService(db)
                            return [
                                {
                                    "id": f.id,
                                    "description": f.description,
                                    "foreshadow_type": getattr(f, "foreshadow_type", "clue") or "clue",
                                    "trigger_keywords": list(getattr(f, "trigger_keywords", []) or []),
                                    "payoff_condition": getattr(f, "payoff_condition", "") or "",
                                    "source_excerpt": getattr(f, "source_excerpt", "") or f.description,
                                    "planted_chapter": f.planted_chapter,
                                }
                                for f in fs.get_unresolved(project_id)
                            ]
        except Exception as e:
            logger.warning(f"Failed to get unresolved foreshadowing: {e}")
        return []
