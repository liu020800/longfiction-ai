import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field, model_validator

DEFAULT_MODEL = "gpt-4o-mini"

ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    PROJECT_NAME: str = "LongFiction-AI"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    LLM_DEFAULT_MODEL: str = DEFAULT_MODEL
    LLM_PLANNER_MODEL: str = DEFAULT_MODEL
    LLM_WRITER_MODEL: str = DEFAULT_MODEL
    LLM_STYLE_MODEL: str = DEFAULT_MODEL
    LLM_CHECK_MODEL: str = DEFAULT_MODEL

    LLM_API_KEY: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    LLM_API_BASE: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("LLM_API_BASE", "OPENAI_API_BASE"))
    LLM_USE_RESPONSE_FORMAT: bool = False
    LLM_TIMEOUT_SECONDS: int = 120
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BASE_DELAY: float = 1.0
    # P0-2 / P1-2: 新增 LLM 调用稳定性配置
    LLM_PROVIDER: str = Field(
        default="openai_compatible",
        validation_alias=AliasChoices("LLM_PROVIDER", "MODEL_PROVIDER"),
    )
    LLM_JSON_MODE_POLICY: str = "auto"  # auto | force | off
    LLM_RETRY_ON_JSON_FAILURE: bool = True
    LLM_MAX_RETRIES_PER_MODEL: int = 2
    LLM_ROUTE_FALLBACK_ENABLED: bool = True
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    FAST_TEST_MODE: bool = False
    SKIP_DEEP_DEAI: bool = False
    SKIP_QUALITY_SCORE: bool = False
    ENABLE_LLM_SCENE_SPLIT: bool = False
    ENABLE_LLM_CHARACTER_UPDATE: bool = False
    ENABLE_API_EMBEDDINGS: bool = False
    ENABLE_UNIFIED_PROJECT_BLUEPRINT: bool = True
    ENABLE_GENERATION_REWRITE: bool = False
    ENABLE_GENERATION_RETRY: bool = True

    ADMIN_USERNAME: str = Field(default="admin", validation_alias=AliasChoices("ADMIN_USERNAME", "LONGFICTION_ADMIN"))
    ADMIN_PASSWORD: str = Field(default="", validation_alias=AliasChoices("ADMIN_PASSWORD", "LONGFICTION_ADMIN_PASSWORD"))

    STATIC_DIR: str = "web"

    MEMORY_SHORT_TERM_SIZE: int = 3
    MEMORY_DECAY_LAMBDA: float = 0.02
    MEMORY_FAISS_INDEX_PATH: str = "data/faiss_index"
    MEMORY_STRUCT_PATH: str = "data/structured_memory.json"

    CHAPTER_MIN_WORDS: int = 2000
    SCENE_TARGET_WORDS: int = 800

    WC_TOLERANCE_PCT: float = 15.0
    WC_LOWER_TOLERANCE: float = 0.85
    WC_UPPER_TOLERANCE: float = 1.15
    WC_MAX_CORRECTION_ATTEMPTS: int = 4
    WC_MIN_SCENE_WORDS: int = 120
    WC_SEVERE_DEVIATION_PCT: float = 30.0
    WC_EXPAND_TOKEN_FACTOR: float = 3.0
    WC_EXPAND_TOKEN_MARGIN: int = 200
    WC_EXPAND_QUALITY_THRESHOLD: float = 0.7
    WC_TRIM_COMPLETENESS_THRESHOLD: float = 0.8
    WC_STYLE_DRIFT_THRESHOLD: float = 0.3
    WC_MAX_CORRECTION_HISTORY: int = 6
    WC_EVAL_TIMEOUT_SECONDS: float = 5.0
    CONFLICT_DENSITY: float = 0.3
    STYLE_PERTURBATION_RATE: float = 0.3
    MULTI_VERSION_COUNT: int = 1

    READBACK_MAX_CHARS: int = 8000
    READBACK_RAG_TOP_K: int = 10
    READBACK_RECENT_WINDOW: int = 5
    READBACK_COMPRESSED_WINDOW: int = 30
    BRAKE_MAX_RETRY: int = 2
    BRAKE_CONSECUTIVE_ZERO_LIMIT: int = 2
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
    ADJUST_LOW_SCORE_THRESHOLD: float = 7.0
    ADJUST_CONSECUTIVE_LOW: int = 3
    ADJUST_MAX_OVERDUE_ARCS: int = 2

    # AI痕迹检测阈值
    AI_TRACE_MAX_PER_CHAPTER: int = 3  # 每章最多允许的AI痕迹短语数
    AI_TRACE_PHRASES: list[str] = [
        "——不是", "，像是", "指节发白", "瞳孔微缩", "瞳孔骤缩",
        "心中涌起", "一股暖流", "倒吸一口凉气",
        # P2 程序级修复：扩展 5 个高频违规模式（《硅基纪元》全文统计中频繁出现）
        "心中一凛", "心中一暖", "不由得", "下意识地", "缓缓开口",
    ]
    AI_TRACE_DENSITY_LIMIT: float = 1.5  # 每千字 AI 痕迹数上限（程序级质量门使用）
    # 动态词频检测：每N字允许出现1次，最低2次
    # P2 修复：300→500（11.6万字里"金属"限值从 387 降到 232，强制更严格的去重）
    WORD_FREQ_CHARS_PER_OCCURRENCE: int = 500
    WORD_FREQ_MIN_THRESHOLD: int = 2

    # ===== 程序级质量门配置（新增）=====
    STRICT_QUALITY_GATES: bool = True  # 全局开关：True=硬拦截，False=WARN 不抛错
    MAX_QUALITY_GATE_RETRIES: int = 2  # 验证门重试次数（首次 + 2 次重试 = 3 轮）
    WC_LOWER_TOLERANCE_LAST: float = 0.95  # 末章字数下限系数（高潮必须达标）
    WORD_COUNT_ABSOLUTE_MIN: int = 200  # 字数绝对下限（硬地板）

    # ===== 业务上限（防止前端误传/UI 误设导致批量推到底）=====
    MAX_TARGET_CHAPTERS: int = 50  # 旧字段保留作兼容，新代码请用 DEFAULT / ABSOLUTE
    MAX_TARGET_CHAPTERS_DEFAULT: int = 50  # 前端 UI 默认上限
    MAX_TARGET_CHAPTERS_ABSOLUTE: int = 200  # 后端 API 绝对上限；超过直接 400

    # ===== P0-3：JWT 密钥独立化 =====
    JWT_SECRET_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "LONGFICTION_JWT_SECRET_KEY"),
    )

    DB_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/novel.db")

    REDIS_URL: str = os.getenv("REDIS_URL", "")
    REDIS_CACHE_TTL: int = 3600
    REDIS_ENABLED: bool = False

    RAG_ES_HOSTS: str = "http://localhost:9200"
    RAG_ES_INDEX_PREFIX: str = "longfiction"
    RAG_ES_ENABLED: bool = False
    RAG_RRF_K: int = 60
    RAG_RERANK_MODEL: str = "bge-reranker-large"
    RAG_RERANK_TIMEOUT: float = 5.0

    CONSOLIDATION_IMPORTANCE_THRESHOLD: float = 0.4
    STYLE_SAMPLE_MIN_CHARS: int = 500

    @model_validator(mode="after")
    def load_openai_compatible_env(self):
        if not self.LLM_API_KEY:
            self.LLM_API_KEY = os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        if self.LLM_API_BASE == "https://api.openai.com/v1":
            env_base = os.getenv("LLM_API_BASE", "") or os.getenv("OPENAI_API_BASE", "")
            if env_base:
                self.LLM_API_BASE = env_base
        default_model = os.getenv("LLM_MODEL", "") or os.getenv("LLM_DEFAULT_MODEL", "")
        if default_model:
            self.LLM_DEFAULT_MODEL = default_model
            if self.LLM_PLANNER_MODEL == DEFAULT_MODEL:
                self.LLM_PLANNER_MODEL = default_model
            if self.LLM_WRITER_MODEL == DEFAULT_MODEL:
                self.LLM_WRITER_MODEL = default_model
            if self.LLM_STYLE_MODEL == DEFAULT_MODEL:
                self.LLM_STYLE_MODEL = default_model
            if self.LLM_CHECK_MODEL == DEFAULT_MODEL:
                self.LLM_CHECK_MODEL = default_model
        return self

    def config_warnings(self) -> list[str]:
        warnings = []
        if not self.LLM_API_KEY:
            warnings.append("LLM API key is not configured")
        models = [self.LLM_PLANNER_MODEL, self.LLM_WRITER_MODEL, self.LLM_STYLE_MODEL, self.LLM_CHECK_MODEL]
        base = self.LLM_API_BASE.lower()
        if "api.openai.com" in base and any(model.startswith("deepseek/") for model in models):
            warnings.append("DeepSeek model id is configured with OpenAI official base URL")
        if "deepseek" in base and any(model.startswith("gpt-") for model in models):
            warnings.append("OpenAI model id is configured with DeepSeek base URL")
        if not self.JWT_SECRET_KEY and not self.DEBUG:
            warnings.append(
                "JWT_SECRET_KEY 未配置：生产环境必须设置至少 32 位的独立密钥，"
                "否则换 LLM Key 会导致全员登出"
            )
        return warnings

    def get_jwt_secret(self) -> str:
        """获取 JWT 签发密钥。

        优先级：
        1. 显式配置的 `JWT_SECRET_KEY`（≥ 32 位）
        2. DEBUG 模式下使用固定开发密钥（仅本地）
        3. 生产环境未配置时抛 ValueError
        """
        if self.JWT_SECRET_KEY and len(self.JWT_SECRET_KEY) >= 32:
            return self.JWT_SECRET_KEY
        if self.DEBUG:
            return "dev-longfiction-jwt-secret-change-me-please-32chars"
        raise ValueError(
            "生产环境必须配置 JWT_SECRET_KEY，长度至少 32 位。"
            "在 .env 中设置 JWT_SECRET_KEY=<至少 32 位随机字符串> 后重启。"
        )

    class Config:
        env_file = str(ENV_FILE_PATH)
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
