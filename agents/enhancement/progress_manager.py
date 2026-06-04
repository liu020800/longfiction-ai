"""REQ-P0-004: Outline anchor and progress quota."""
import logging
from .models import AnchorCategory, AnchorDefinition, QuotaResult, DeviationReport, ProgressSummary
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)


class ProgressManager:
    def __init__(self, config: EnhancementConfig):
        self.config = config
        self.anchors: list[AnchorDefinition] = []
        self.anchor_completions: dict[int, bool] = {}

    def set_anchors(self, anchors: list[AnchorDefinition]):
        self.anchors = anchors
        self.anchor_completions = {a.chapter_index: False for a in anchors}

    def check_quota(self, current_chapter: int, total_chapters: int) -> QuotaResult:
        violations = []
        progress = current_chapter / max(total_chapters, 1)
        interval = total_chapters // 3

        a_count = sum(1 for a in self.anchors if a.category == AnchorCategory.A_CLASS and a.chapter_index <= current_chapter)
        a_expected = max(1, int(progress * sum(1 for a in self.anchors if a.category == AnchorCategory.A_CLASS)))
        if a_count > a_expected + self.config.QUOTA_A_LIMIT:
            violations.append(f"A类锚点已触发{a_count}次，预期{a_expected}次")

        return QuotaResult(with_quota=len(violations) == 0, violations=violations)

    def detect_deviation(self, current_chapter: int, total_chapters: int, actual_progress: float) -> DeviationReport:
        expected = current_chapter / max(total_chapters, 1)
        deviation = abs(actual_progress - expected)
        suggestion = ""
        if deviation > self.config.DEVIATION_THRESHOLD:
            if actual_progress > expected:
                suggestion = "剧情推进过快，建议增加过渡章节或延缓主线节奏"
            else:
                suggestion = "剧情推进偏慢，建议加快主线推进或减少日常章节"
        return DeviationReport(deviation_percent=round(deviation * 100, 1), suggestion=suggestion)

    def check_anchor_not_skipped(self, chapter_index: int) -> bool:
        for a in self.anchors:
            if a.category == AnchorCategory.A_CLASS and a.chapter_index == chapter_index:
                return True
        return True

    def get_progress_summary(self) -> ProgressSummary:
        total = len(self.anchors)
        completed = sum(1 for v in self.anchor_completions.values() if v)
        a_total = sum(1 for a in self.anchors if a.category == AnchorCategory.A_CLASS)
        a_done = sum(1 for a in self.anchors if a.category == AnchorCategory.A_CLASS and self.anchor_completions.get(a.chapter_index, False))
        b_total = sum(1 for a in self.anchors if a.category == AnchorCategory.B_CLASS)
        b_done = sum(1 for a in self.anchors if a.category == AnchorCategory.B_CLASS and self.anchor_completions.get(a.chapter_index, False))
        c_total = sum(1 for a in self.anchors if a.category == AnchorCategory.C_CLASS)
        c_done = sum(1 for a in self.anchors if a.category == AnchorCategory.C_CLASS and self.anchor_completions.get(a.chapter_index, False))
        return ProgressSummary(
            total_anchors=total, completed_anchors=completed,
            a_progress=a_done / max(a_total, 1),
            b_progress=b_done / max(b_total, 1),
            c_progress=c_done / max(c_total, 1),
        )

    def update_anchor_completion(self, chapter_index: int, completed: bool = True):
        self.anchor_completions[chapter_index] = completed
        for a in self.anchors:
            if a.chapter_index == chapter_index:
                a.completed = completed

    def get_state(self) -> dict:
        return {
            "anchors": [a.model_dump() for a in self.anchors],
            "anchor_completions": self.anchor_completions,
        }

    def restore_state(self, state: dict):
        self.anchors = [AnchorDefinition(**a) for a in state.get("anchors", [])]
        self.anchor_completions = state.get("anchor_completions", {})
