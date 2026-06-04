import logging
from typing import Optional
from core.llm_router import call_llm, TaskType
from core.word_counter import count_chinese_words, _split_sentences
from core.config import settings

logger = logging.getLogger(__name__)

_MIGRATION_SYSTEM = """你是一位风格迁移专家。你需要将文本从一种风格迁移到另一种风格，同时完整保留情节骨架和人物设定。
要求：
- 保留所有冲突事件、角色行为、世界规则
- 只调整语言风格维度（句式、用词、节奏、修辞）
- 不改变情节走向和因果关系
- 直接输出迁移后的完整文本"""


class StyleMigrator:
    def __init__(self):
        self.plot_threshold = getattr(settings, 'STYLE_MIGRATION_PLOT_THRESHOLD', 0.7)

    async def migrate(
        self,
        text: str,
        target_style_name: str,
        target_style_desc: str = "",
        source_style_desc: str = "",
    ) -> str:
        if not text or count_chinese_words(text) < 50:
            return text

        prompt = f"""请将以下文本从「{source_style_desc or "当前风格"}」迁移到「{target_style_name}」风格。

目标风格描述：{target_style_desc}

严格要求：
1. 完整保留所有情节事件和人物行为，一个事件都不能删
2. 只调整风格维度：句式选择、用词偏好、叙事节奏、修辞方式
3. 保持人物性格和对话口吻与风格一致
4. 不改变因果关系和事件顺序

原文：
{text}"""

        try:
            migrated = await call_llm(
                TaskType.REWRITE, prompt,
                system=_MIGRATION_SYSTEM,
                temperature=0.6,
                max_tokens=len(text) * 2,
            )
            if not migrated or count_chinese_words(migrated) < count_chinese_words(text) * 0.7:
                logger.warning("Migrated text too short, keeping original")
                return text
            return migrated
        except Exception as e:
            logger.warning(f"Style migration failed: {e}")
            return text

    def check_plot_skeleton(self, original: str, migrated: str) -> float:
        orig_keywords = set()
        for kw in ["冲突", "战斗", "发现", "真相", "暴露", "背叛", "联盟", "死亡", "复活", "获得", "失去", "修炼", "突破"]:
            if kw in original:
                orig_keywords.add(kw)

        if not orig_keywords:
            return 1.0

        retained = sum(1 for kw in orig_keywords if kw in migrated)
        similarity = retained / len(orig_keywords)
        return similarity
