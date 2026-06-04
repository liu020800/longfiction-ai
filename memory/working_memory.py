import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SceneContext:
    scene_id: str = ""
    present_characters: list[str] = field(default_factory=list)
    location: str = ""
    perception_focus: str = ""
    active_foreshadowing: list[str] = field(default_factory=list)
    emotional_state: str = "neutral"


class WorkingMemory:
    def __init__(self):
        self.scene: SceneContext = SceneContext()

    def update_on_scene_switch(self, new_scene: SceneContext):
        old_scene_id = self.scene.scene_id
        self.scene = new_scene
        logger.info(f"WorkingMemory scene switch: {old_scene_id} -> {new_scene.scene_id}")

    def update_field(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.scene, key):
                setattr(self.scene, key, value)

    def get_context_text(self) -> str:
        parts = []
        if self.scene.scene_id:
            parts.append(f"当前场景: {self.scene.scene_id}")
        if self.scene.present_characters:
            parts.append(f"在场人物: {'、'.join(self.scene.present_characters)}")
        if self.scene.location:
            parts.append(f"位置: {self.scene.location}")
        if self.scene.perception_focus:
            parts.append(f"感知重点: {self.scene.perception_focus}")
        if self.scene.active_foreshadowing:
            parts.append(f"活跃伏笔: {'、'.join(self.scene.active_foreshadowing)}")
        if self.scene.emotional_state != "neutral":
            parts.append(f"情绪基调: {self.scene.emotional_state}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return asdict(self.scene)

    def from_dict(self, data: dict):
        self.scene = SceneContext(
            scene_id=data.get("scene_id", ""),
            present_characters=data.get("present_characters", []),
            location=data.get("location", ""),
            perception_focus=data.get("perception_focus", ""),
            active_foreshadowing=data.get("active_foreshadowing", []),
            emotional_state=data.get("emotional_state", "neutral"),
        )
