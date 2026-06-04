"""Pydantic data models for the enhancement subsystem."""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


class RetrievedFragment(BaseModel):
    chapter_index: int
    text: str
    score: float
    source: str = "rag"


class HierarchicalMemory(BaseModel):
    recent_full: list[str] = Field(default_factory=list)
    compressed_summaries: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)


class ReadbackResult(BaseModel):
    context_text: str
    fragment_count: int
    total_chars: int
    used_rag: bool = True


class UnresolvedIssue(BaseModel):
    description: str
    introduced_chapter: int
    priority: str = "minor"


class BrakeResult(BaseModel):
    blocked: bool
    reason: str = ""
    core_conflict_resolved: bool = False
    new_issues_count: int = 0
    need_regenerate: bool = False


class EventCategory(str, Enum):
    CONFLICT = "conflict"
    SATISFY = "satisfy"
    REVEAL = "reveal"
    TWIST = "twist"
    DAILY = "daily"


class ClassifiedEvent(BaseModel):
    chapter_index: int
    category: EventCategory
    description: str


class CooldownState(BaseModel):
    last_chapter: dict[str, int] = Field(default_factory=dict)


class CooldownResult(BaseModel):
    violations: list[str] = Field(default_factory=list)
    allowed_categories: list[EventCategory] = Field(default_factory=list)


class AnchorCategory(str, Enum):
    A_CLASS = "a_class"
    B_CLASS = "b_class"
    C_CLASS = "c_class"


class AnchorDefinition(BaseModel):
    chapter_index: int
    category: AnchorCategory
    description: str
    completed: bool = False


class QuotaResult(BaseModel):
    within_quota: bool
    violations: list[str] = Field(default_factory=list)


class DeviationReport(BaseModel):
    deviation_percent: float
    suggestion: str = ""


class ProgressSummary(BaseModel):
    total_anchors: int
    completed_anchors: int
    a_progress: float
    b_progress: float
    c_progress: float


class StructureCheckResult(BaseModel):
    compliant: bool
    issues: list[str] = Field(default_factory=list)
    hook_present_opening: bool = False
    hook_present_ending: bool = False


class InfoGapState(BaseModel):
    reader_knows: list[str] = Field(default_factory=list)
    character_knows: list[str] = Field(default_factory=list)
    reader_wants_to_know: list[str] = Field(default_factory=list)


class InfoGapOpportunity(BaseModel):
    info: str
    drama_type: str = "suspense"


class ArcLevel(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class SuspenseArc(BaseModel):
    arc_id: str
    level: ArcLevel
    description: str
    planted_chapter: int
    target_close_chapter: int
    current_chapter: int = 0
    closed: bool = False
    overdue: bool = False
    resolved_chapter: Optional[int] = None
    resolved_reason: str = ""


class EmotionCurve(BaseModel):
    start_intensity: float = 5.0
    peak_intensity: float = 8.0
    end_intensity: float = 6.0


class DensityCheckResult(BaseModel):
    compliant: bool
    violations: list[str] = Field(default_factory=list)


class RhythmDeviationResult(BaseModel):
    deviation: float
    warning: str = ""


class TechniqueDefinition(BaseModel):
    name: str
    description: str
    examples: list[str] = Field(default_factory=list)


class ShowTellPair(BaseModel):
    tell: str
    show: str


class AITraceType(str, Enum):
    LOGIC_JUMP = "logic_jump"
    EMOTION_JUMP = "emotion_jump"
    UNIFORM_SENTENCE = "uniform_sentence"
    FLAT_DIALOGUE = "flat_dialogue"
    UNNATURAL_TRANSITION = "unnatural_transition"
    DENSITY_ANOMALY = "density_anomaly"
    REPETITIVE_PATTERN = "repetitive_pattern"


class MarkedSegment(BaseModel):
    start_idx: int
    end_idx: int
    trace_type: AITraceType
    description: str


class SecondPassResult(BaseModel):
    marked_segments: list[MarkedSegment] = Field(default_factory=list)
    rewritten_text: str = ""
    changes_made: bool = False


class Shortfall(BaseModel):
    dimension: str
    score: float
    suggestion: str = ""


class QualityScoreResult(BaseModel):
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    composite_score: float = 0.0
    shortfalls: list[Shortfall] = Field(default_factory=list)
    should_regenerate: bool = False


class OutlineAdjustmentPlan(BaseModel):
    plan_id: str = ""
    reason: str = ""
    changes: list[str] = Field(default_factory=list)
    confirmed: bool = False
    created_at: Optional[datetime] = None


class StoryThreadStatus(str, Enum):
    PLANTED = "planted"
    ACTIVE = "active"
    RESOLVING = "resolving"
    CLOSED = "closed"


class StoryThreadType(str, Enum):
    FORESHADOW = "伏笔"
    SUSPENSE = "悬念"
    INFO_GAP = "信息差"
    CHAR_ARC = "人物弧线"
    DEBT = "剧情债务"


class ThreadAdvanceLog(BaseModel):
    chapter: int
    note: str


class StoryThread(BaseModel):
    thread_id: str
    type: StoryThreadType = StoryThreadType.FORESHADOW
    status: StoryThreadStatus = StoryThreadStatus.PLANTED
    planted_chapter: int
    description: str
    resolution_hint: str = ""
    must_resolve_by: int = 0          # 硬性截止章节（0=无截止）
    urgency_score: int = 0            # 动态计算：current - planted
    advance_log: list[ThreadAdvanceLog] = Field(default_factory=list)
    source: str = ""                  # "db_foreshadow" | "open_intent" | "suspense_arc" | "llm_extract"


class EnhancementState(BaseModel):
    unresolved_issues: list[UnresolvedIssue] = Field(default_factory=list)
    consecutive_zero_count: int = 0
    cooldown_state: CooldownState = Field(default_factory=CooldownState)
    anchors: list[AnchorDefinition] = Field(default_factory=list)
    anchor_completions: dict[int, bool] = Field(default_factory=dict)
    info_gap_state: InfoGapState = Field(default_factory=InfoGapState)
    suspense_arcs: list[SuspenseArc] = Field(default_factory=list)
    quality_scores_history: list[dict] = Field(default_factory=list)
    readback_cache: dict = Field(default_factory=dict)
    thread_pool_threads: list[StoryThread] = Field(default_factory=list)
