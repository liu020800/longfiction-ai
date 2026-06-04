import logging
from .models import InfoGapState, InfoGapOpportunity
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

class InfoGapManager:
    def __init__(self, config: EnhancementConfig):
        self.config = config
        self.state = InfoGapState()
    
    def initialize_from_setting(self, world_setting: dict, characters: list[dict]):
        self.state.reader_knows = []
        self.state.character_knows = []
        self.state.reader_wants_to_know = []

        if world_setting:
            rules = world_setting.get("rules", [])
            for r in rules[:4]:
                self.state.reader_knows.append(f"世界规则: {r}")
            # 世界观势力
            factions = world_setting.get("factions", world_setting.get("forces", []))
            if isinstance(factions, list):
                for f in factions[:3]:
                    if isinstance(f, dict):
                        fname = f.get("name", "")
                        fdesc = f.get("description", "")
                        if fname:
                            self.state.reader_knows.append(f"势力: {fname}{' - ' + fdesc[:40] if fdesc else ''}")
                    elif isinstance(f, str) and f.strip():
                        self.state.reader_knows.append(f"势力: {f.strip()}")
            # 关键地点
            locations = world_setting.get("key_locations", world_setting.get("locations", []))
            if isinstance(locations, list):
                for loc in locations[:3]:
                    if isinstance(loc, dict):
                        lname = loc.get("name", "")
                        if lname:
                            self.state.reader_knows.append(f"地点: {lname}")
                    elif isinstance(loc, str) and loc.strip():
                        self.state.reader_knows.append(f"地点: {loc.strip()}")
            # 历史背景
            history = world_setting.get("history", [])
            if isinstance(history, list):
                for h in history[:2]:
                    if isinstance(h, str) and h.strip():
                        self.state.reader_knows.append(f"历史: {h.strip()[:60]}")
            # 核心悬念
            self.state.reader_wants_to_know.append("主角的真正实力和潜力")
            self.state.reader_wants_to_know.append("核心冲突的最终走向")
            if world_setting.get("mystery") or world_setting.get("core_conflict"):
                self.state.reader_wants_to_know.append(world_setting.get("mystery", world_setting.get("core_conflict", ""))[:60])

        for c in characters[:5]:
            name = c.get("name", "")
            goal = c.get("goal", "")
            role = c.get("role", "")
            if name:
                if goal:
                    self.state.character_knows.append(f"{name}的目标: {goal}")
                if role:
                    self.state.character_knows.append(f"{name}的身份: {role}")
                # 角色的秘密或隐藏信息
                secret = c.get("secret", c.get("hidden_past", ""))
                if secret:
                    self.state.reader_wants_to_know.append(f"{name}的秘密")
    
    def get_info_gap_state(self) -> InfoGapState:
        return self.state
    
    def generate_info_gap_instruction(self) -> str:
        gaps = self.detect_info_gaps()
        if not gaps:
            return ""
        instructions = ["\n【信息差利用建议】"]
        for g in gaps[:3]:
            instructions.append(f"- {g.drama_type}：利用信息差「{g.info}」制造戏剧张力")
        if not self.state.reader_wants_to_know:
            instructions.append("- 读者没有待解之谜，本章必须引入至少一个新悬念")
        return "\n".join(instructions) + "\n"
    
    def update_after_chapter(self, chapter_text: str, chapter_index: int):
        revealed_keywords = ["揭示", "真相", "暴露", "坦白", "发现", "终于明白", "原来"]
        for kw in revealed_keywords:
            if kw in chapter_text:
                for item in list(self.state.reader_wants_to_know[:3]):
                    self.state.reader_wants_to_know.remove(item)
                    self.state.reader_knows.append(item)
                    break
        
        suspense_keywords = ["谜团", "疑问", "秘密", "隐藏", "未知", "可疑"]
        for kw in suspense_keywords:
            if kw in chapter_text:
                new_info = f"第{chapter_index}章引入的{kw}"
                self.state.reader_wants_to_know.append(new_info)
                break
        
        self.check_reader_want_to_know(chapter_index)
    
    def check_reader_want_to_know(self, chapter_index: int):
        if not self.state.reader_wants_to_know:
            self.state.reader_wants_to_know.append(f"第{chapter_index}章后产生的新悬念")

    def settle_at_story_end(self, final_summary: str = ""):
        """故事完结后，清理泛化悬念，保留少量余韵信息到已知区。"""
        resolved = []
        for item in list(self.state.reader_wants_to_know):
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            if cleaned not in self.state.reader_knows:
                resolved.append(cleaned)
        self.state.reader_wants_to_know = []
        if final_summary:
            note = f"终局结算: {final_summary[:120]}"
            if note not in self.state.reader_knows:
                self.state.reader_knows.append(note)
        for item in resolved[:5]:
            summary = f"终局已处理: {item}"
            if summary not in self.state.reader_knows:
                self.state.reader_knows.append(summary)
    
    def detect_info_gaps(self) -> list[InfoGapOpportunity]:
        gaps = []
        reader_only = set(self.state.reader_knows) - set(self.state.character_knows)
        char_only = set(self.state.character_knows) - set(self.state.reader_knows)
        
        for info in list(reader_only)[:2]:
            gaps.append(InfoGapOpportunity(info=info, drama_type="戏剧反讽"))
        for info in list(char_only)[:2]:
            gaps.append(InfoGapOpportunity(info=info, drama_type="悬念"))
        for info in self.state.reader_wants_to_know[:2]:
            gaps.append(InfoGapOpportunity(info=info, drama_type="驱动力"))
        
        return gaps
    
    def get_state(self) -> dict:
        return {"info_gap_state": self.state.model_dump()}
    
    def restore_state(self, state: dict):
        if "info_gap_state" in state:
            self.state = InfoGapState(**state["info_gap_state"])
