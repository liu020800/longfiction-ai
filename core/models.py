from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum


class TaskType(str, Enum):
    PLAN = "plan"
    WRITE = "write"
    REWRITE = "rewrite"
    CHECK = "check"
    WORLD = "world"
    CHARACTER = "character"
    PLOT = "plot"


class VolumeOutline(BaseModel):
    volume: str
    chapters: list["ChapterOutline"] = Field(default_factory=list)


class ChapterOutline(BaseModel):
    title: str
    goal: str
    conflict: str
    scenes: list["SceneOutline"] = Field(default_factory=list)


class SceneOutline(BaseModel):
    description: str
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    mood: str = ""
    target_words: int = 800
    tension_weight: float = 1.0
    sensory_focus: str = ""


class WorldSetting(BaseModel):
    cultivation_system: str = ""
    factions: list[dict] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    locations: list[dict] = Field(default_factory=list)


class CharacterSheet(BaseModel):
    name: str
    goal: str = ""
    personality: list[str] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    status: dict = Field(default_factory=dict)
    memory: list[str] = Field(default_factory=list)
    appearance: str = ""
    abilities: list[str] = Field(default_factory=list)
    voice: dict = Field(default_factory=dict)


class PlotArc(BaseModel):
    arc_type: str = "main"
    description: str
    progress: float = 0.0
    conflicts: list[str] = Field(default_factory=list)
    resolution: str = ""


class ChapterDraft(BaseModel):
    volume_index: int
    chapter_index: int
    title: str
    content: str
    word_count: int = 0
    consistency_score: float = 1.0
    version: int = 1
    finalized: bool = False
    finalize_errors: list[str] = Field(default_factory=list)
    intent: dict = Field(default_factory=dict)
    observations: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_must_be_meaningful(cls, v: str) -> str:
        """P2 程序级修复：标题不能为空或过短。"""
        if not v or not v.strip():
            raise ValueError("ChapterDraft.title cannot be empty")
        if len(v.strip()) < 2:
            raise ValueError("ChapterDraft.title must be ≥ 2 non-blank chars")
        return v.strip()

    @field_validator("content")
    @classmethod
    def content_must_be_nonempty(cls, v: str) -> str:
        """P2 程序级修复：正文不能为空。"""
        if not v or not v.strip():
            raise ValueError("ChapterDraft.content cannot be empty")
        return v


class ConsistencyReport(BaseModel):
    is_consistent: bool = True
    issues: list[str] = Field(default_factory=list)
    ooc_characters: list[str] = Field(default_factory=list)
    world_conflicts: list[str] = Field(default_factory=list)
    logic_errors: list[str] = Field(default_factory=list)
    score: float = 1.0


class GenerationRequest(BaseModel):
    outline: str
    genre: str = "urban_fantasy"
    style: str = "web_novel"
    target_chapters: int = 100
    words_per_chapter: int = 2000


VolumeOutline.model_rebuild()
ChapterOutline.model_rebuild()
SceneOutline.model_rebuild()
