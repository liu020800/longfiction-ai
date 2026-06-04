"""Configuration for the enhancement subsystem."""
from pydantic_settings import BaseSettings


class EnhancementConfig(BaseSettings):
    READBACK_MAX_CHARS: int = 8000
    READBACK_RAG_TOP_K: int = 10
    READBACK_RECENT_WINDOW: int = 5
    READBACK_COMPRESSED_WINDOW: int = 30

    BRAKE_MAX_RETRY: int = 2
    BRAKE_CONSECUTIVE_ZERO_LIMIT: int = 8

    COOLDOWN_CONFLICT: int = 2
    COOLDOWN_SATISFY: int = 2
    COOLDOWN_REVEAL: int = 3
    COOLDOWN_TWIST: int = 2
    COOLDOWN_DAILY: int = 0

    QUOTA_A_LIMIT: int = 1
    QUOTA_B_LIMIT_PERCENT: float = 1.2
    QUOTA_C_LIMIT_PERCENT: float = 1.5
    DEVIATION_THRESHOLD: float = 0.2

    STRUCTURE_HOOK_RATIO: float = 0.20
    STRUCTURE_DEV_RATIO: float = 0.55
    STRUCTURE_CLIMAX_RATIO: float = 0.17
    STRUCTURE_TAIL_RATIO: float = 0.08

    MIN_ACTIVE_ARCS: int = 3
    SHORT_ARC_MAX: int = 3
    MEDIUM_ARC_MAX: int = 8
    OVERDUE_QUALITY_PENALTY: float = 0.5

    DENSITY_MAX_CONSECUTIVE: int = 3
    RHYTHM_DEVIATION_THRESHOLD: float = 0.3

    QUALITY_REGENERATE_THRESHOLD: float = 6.0
    QUALITY_SHORTFALL_THRESHOLD: float = 4.0
    QUALITY_WEIGHTS: dict = {
        "opening": 1.0, "plot": 1.2, "character": 1.0, "dialogue": 1.0,
        "suspense": 1.1, "pacing": 1.0, "show_dont_tell": 1.1, "language": 1.0, "coherence": 1.0,
        "ai_naturalness": 1.3
    }

    ADJUST_LOW_SCORE_THRESHOLD: float = 7.0
    ADJUST_CONSECUTIVE_LOW: int = 3
    ADJUST_MAX_OVERDUE_ARCS: int = 2

    # 线程池配置
    THREAD_URGENCY_THRESHOLD: int = 5       # urgency >= 此值时标记为"必须推进"
    THREAD_DEFAULT_DEADLINE: int = 12       # 默认截止章节数（planted + N）
    THREAD_MAX_ACTIVE: int = 20             # 最大活跃线程数
    THREAD_MANDATE_CRITICAL_MAX: int = 3    # 每章最多注入的"必须关闭"任务数
    THREAD_MANDATE_URGENT_MAX: int = 5      # 每章最多注入的"必须推进"任务数

    class Config:
        env_prefix = "ENHANCE_"
        extra = "ignore"
