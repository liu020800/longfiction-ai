import logging
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

DEFAULT_ENTRY_MODES = [
    {"name": "行动中开场", "description": "角色正在做某事，读者被直接拉入场景", "instruction": "本章开头使用行动中开场：角色正在执行某个动作，直接进入事件现场，不铺垫背景。"},
    {"name": "反常情境", "description": "出现违反常理的情况引发好奇", "instruction": "本章开头使用反常情境：呈现一个违反常理或预期的情境，引发读者好奇心。"},
    {"name": "震撼对话", "description": "以一句令人震惊的对话开场", "instruction": "本章开头使用震撼对话：以一句出人意料或震撼的对话开场，立即制造紧张感。"},
    {"name": "倒计时开场", "description": "时间紧迫感推动叙事", "instruction": "本章开头使用倒计时开场：强调时间紧迫，角色必须在有限时间内行动。"},
    {"name": "回忆切入", "description": "从角色的关键记忆切入", "instruction": "本章开头使用回忆切入：从角色的一个关键记忆或闪回切入，与当前情节形成呼应。"},
    {"name": "物件特写", "description": "聚焦一个关键物件展开叙事", "instruction": "本章开头使用物件特写：聚焦描写一个与情节密切相关的物件，由此展开叙事。"},
    {"name": "悬念预置", "description": "先抛出悬念结果再回溯过程", "instruction": "本章开头使用悬念预置：先暗示或展示某个结果，再回溯过程，制造悬念。"},
    {"name": "对比反衬", "description": "用强烈对比场景开场", "instruction": "本章开头使用对比反衬：用与前一章或预期强烈反差的场景开场，制造冲击感。"},
]

class EntryModeManager:
    def __init__(self, config: EnhancementConfig, custom_modes: list[dict] | None = None):
        self.config = config
        self.modes = custom_modes if custom_modes else DEFAULT_ENTRY_MODES
        if not self.modes:
            self.modes = DEFAULT_ENTRY_MODES
            logger.warning("叙事入口模式列表为空，使用默认8种模式")
    
    def get_mode_for_chapter(self, chapter_index: int) -> dict:
        idx = (chapter_index - 1) % len(self.modes)
        return self.modes[idx]
    
    def generate_entry_constraint(self, chapter_index: int) -> str:
        mode = self.get_mode_for_chapter(chapter_index)
        return f"\n【叙事入口模式】第{chapter_index}章\n{mode['instruction']}\n"
    
    def get_mode_description(self, chapter_index: int) -> str:
        mode = self.get_mode_for_chapter(chapter_index)
        return f"{mode['name']}：{mode['description']}"
    
    def get_state(self) -> dict:
        return {"modes": self.modes}
    
    def restore_state(self, state: dict):
        if "modes" in state and state["modes"]:
            self.modes = state["modes"]
