"""REQ-P0-002: Anti-resolution brake."""
import logging
from .models import BrakeResult, UnresolvedIssue
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

CORE_CONFLICT_KEYWORDS = ["最终战胜", "彻底击败", "完全解决", "永远消灭", "彻底消灭", "终于找到", "真相大白", "阴谋瓦解"]


class AntiResolutionBrake:
    def __init__(self, config: EnhancementConfig, llm_call=None):
        self.config = config
        self.llm_call = llm_call
        self.unresolved_issues: list[UnresolvedIssue] = []
        self.consecutive_zero_count: int = 0
        self._core_conflict: str = ""

    def set_core_conflict(self, conflict: str):
        self._core_conflict = conflict

    def check_and_intercept(self, chapter_text: str, chapter_index: int, total_chapters: int, context_tags: list[str] | None = None) -> BrakeResult:
        context_tags = context_tags or []
        is_special_context = any(t in context_tags for t in ["dream", "flashback", "memory", "legend"])
        is_finale = chapter_index >= total_chapters - 1
        core_resolved = self._detect_core_conflict_resolution(chapter_text)
        new_count = self._count_new_unresolved_issues(chapter_text, chapter_index)

        if new_count == 0 and not is_finale:
            self.consecutive_zero_count += 1
        else:
            self.consecutive_zero_count = 0

        if not is_finale:
            if core_resolved:
                if is_special_context:
                    logger.info(f"  已死/幻境上下文覆盖: 核心冲突关键词出现在特殊场景（{context_tags}），不拦截")
                else:
                    return BrakeResult(blocked=True, reason="非终局章节解决核心冲突", core_conflict_resolved=True, new_issues_count=new_count, need_regenerate=True)
            if self.consecutive_zero_count >= self.config.BRAKE_CONSECUTIVE_ZERO_LIMIT and not is_special_context:
                return BrakeResult(blocked=True, reason=f"连续{self.consecutive_zero_count}章无新增未解决问题", new_issues_count=0, need_regenerate=True)
        else:
            if new_count == 0 and len(self.unresolved_issues) > 0:
                pass

        return BrakeResult(blocked=False, core_conflict_resolved=core_resolved, new_issues_count=new_count)

    def _detect_core_conflict_resolution(self, text: str) -> bool:
        for kw in CORE_CONFLICT_KEYWORDS:
            if kw in text:
                return True
        return False

    def _count_new_unresolved_issues(self, text: str, chapter_index: int) -> int:
        new_issues_keywords = ["谜团", "疑问", "隐患", "困境", "危机", "威胁", "秘密", "未知", "隐藏", "阴谋"]
        count = 0
        for kw in new_issues_keywords:
            count += text.count(kw)
        estimated = min(count // 3, 5)
        for i in range(estimated):
            self.unresolved_issues.append(UnresolvedIssue(description=f"章节{chapter_index}引入的问题", introduced_chapter=chapter_index))
        return estimated

    def generate_brake_instruction(self, chapter_index: int, total_chapters: int) -> str:
        is_finale = chapter_index >= total_chapters - 1
        if is_finale:
            return ""
        return (
            "\n【反向刹车约束】\n"
            "1. 不要在本章解决核心矛盾或主线冲突\n"
            "2. 必须保留悬念，制造新的次要障碍\n"
            "3. 让角色的短期目标落空或延后\n"
            "4. 章末必须留下一个让读者想翻下一页的钩子\n"
            "5. 本章必须引入至少一个未解决的新问题\n"
        )

    def get_state(self) -> dict:
        return {
            "unresolved_issues": [i.model_dump() for i in self.unresolved_issues],
            "consecutive_zero_count": self.consecutive_zero_count,
            "core_conflict": self._core_conflict,
        }

    def restore_state(self, state: dict):
        self.unresolved_issues = [UnresolvedIssue(**i) for i in state.get("unresolved_issues", [])]
        self.consecutive_zero_count = state.get("consecutive_zero_count", 0)
        self._core_conflict = state.get("core_conflict", "")
