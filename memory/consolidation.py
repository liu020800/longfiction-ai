import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from memory.working_memory import WorkingMemory, SceneContext
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from memory.structured import StructuredMemory
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationCandidate:
    text: str
    source: str
    importance: float = 0.5
    embedding: Optional[list] = None
    meta: dict = field(default_factory=dict)


class ImportanceScorer:
    CHAR_EVENT_KEYWORDS = ["突破", "死亡", "觉醒", "背叛", "结盟", "分离", "重逢", "变身", "晋级", "失败"]
    PLOT_KEYWORDS = ["秘密", "真相", "伏笔", "线索", "转折", "危机", "决战", "阴谋", "预言", "契约"]
    EMOTION_KEYWORDS = ["震惊", "愤怒", "悲伤", "狂喜", "恐惧", "绝望", "希望", "感动"]

    def score(self, text: str, context: dict = None) -> float:
        context = context or {}
        base = 0.3
        char_hits = sum(1 for kw in self.CHAR_EVENT_KEYWORDS if kw in text)
        plot_hits = sum(1 for kw in self.PLOT_KEYWORDS if kw in text)
        emotion_hits = sum(1 for kw in self.EMOTION_KEYWORDS if kw in text)

        char_boost = min(char_hits * 0.15, 0.3)
        plot_boost = min(plot_hits * 0.12, 0.25)
        emotion_boost = min(emotion_hits * 0.08, 0.15)

        if context.get("is_climax"):
            base += 0.15
        if context.get("has_new_character"):
            base += 0.1
        if context.get("foreshadow_planted"):
            base += 0.1
        if context.get("foreshadow_resolved"):
            base += 0.12

        return min(1.0, base + char_boost + plot_boost + emotion_boost)


class MemoryConsolidation:
    def __init__(
        self,
        working_memory: WorkingMemory,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        structured: StructuredMemory,
        embed_fn=None,
    ):
        self.wm = working_memory
        self.stm = short_term
        self.ltm = long_term
        self.structured = structured
        self.embed_fn = embed_fn
        self.scorer = ImportanceScorer()
        self._pending: list[ConsolidationCandidate] = []

    def extract_from_working_memory(self, chapter_content: str = "", chapter_idx: int = 0) -> list[ConsolidationCandidate]:
        candidates = []
        scene = self.wm.scene

        if scene.present_characters and scene.location:
            text = f"第{chapter_idx}章场景: {', '.join(scene.present_characters)} 在 {scene.location}"
            if scene.emotional_state and scene.emotional_state != "neutral":
                text += f", 情绪基调: {scene.emotional_state}"
            candidates.append(ConsolidationCandidate(
                text=text,
                source="working_memory",
                meta={"type": "scene_snapshot", "chapter": chapter_idx},
            ))

        if scene.active_foreshadowing:
            for fs in scene.active_foreshadowing:
                candidates.append(ConsolidationCandidate(
                    text=f"活跃伏笔(第{chapter_idx}章): {fs}",
                    source="working_memory",
                    importance=0.7,
                    meta={"type": "foreshadowing", "chapter": chapter_idx},
                ))

        for c in candidates:
            c.importance = self.scorer.score(c.text, {"chapter": chapter_idx})

        return candidates

    def extract_from_chapter(self, chapter_content: str, chapter_title: str, chapter_idx: int, context: dict = None) -> list[ConsolidationCandidate]:
        context = context or {}
        candidates = []

        summary_text = chapter_content[:600] if len(chapter_content) > 600 else chapter_content
        importance = self.scorer.score(chapter_content, context)

        candidates.append(ConsolidationCandidate(
            text=f"【{chapter_title}】{summary_text}",
            source="chapter",
            importance=importance,
            meta={"type": "chapter_content", "chapter": chapter_idx, "title": chapter_title},
        ))

        return candidates

    async def consolidate(self, chapter_content: str, chapter_title: str, chapter_idx: int, context: dict = None) -> dict:
        context = context or {}
        wm_candidates = self.extract_from_working_memory(chapter_content, chapter_idx)
        ch_candidates = self.extract_from_chapter(chapter_content, chapter_title, chapter_idx, context)

        all_candidates = wm_candidates + ch_candidates
        promoted_to_ltm = 0
        skipped = 0

        importance_threshold = getattr(settings, 'CONSOLIDATION_IMPORTANCE_THRESHOLD', 0.4)

        for candidate in all_candidates:
            if candidate.importance < importance_threshold:
                skipped += 1
                continue

            if self._is_duplicate(candidate):
                skipped += 1
                continue

            embedding = None
            if self.embed_fn:
                try:
                    embedding = await self.embed_fn(candidate.text)
                except Exception as e:
                    logger.warning(f"Failed to embed consolidation candidate: {e}")

            if embedding is not None:
                self.ltm.add(
                    text=candidate.text,
                    embedding=embedding,
                    meta={
                        **candidate.meta,
                        "importance": candidate.importance,
                        "source": candidate.source,
                    },
                )
                promoted_to_ltm += 1
            else:
                self._pending.append(candidate)

        result = {
            "total_candidates": len(all_candidates),
            "promoted_to_ltm": promoted_to_ltm,
            "skipped": skipped,
            "pending": len(self._pending),
        }
        logger.info(f"Memory consolidation for chapter {chapter_idx}: {result}")
        return result

    def _is_duplicate(self, candidate: ConsolidationCandidate) -> bool:
        existing_texts = self.ltm.get_all_texts()
        candidate_prefix = candidate.text[:80]
        for existing in existing_texts[-50:]:
            if candidate_prefix in existing or existing[:80] in candidate.text:
                return True
        return False

    async def flush_pending(self):
        if not self._pending or not self.embed_fn:
            return 0
        flushed = 0
        remaining = []
        for candidate in self._pending:
            try:
                embedding = await self.embed_fn(candidate.text)
                if embedding is not None:
                    self.ltm.add(
                        text=candidate.text,
                        embedding=embedding,
                        meta={**candidate.meta, "importance": candidate.importance, "source": candidate.source},
                    )
                    flushed += 1
                else:
                    remaining.append(candidate)
            except Exception:
                remaining.append(candidate)
        self._pending = remaining
        return flushed
