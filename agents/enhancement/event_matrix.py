"""REQ-P0-003: Event matrix and cooldown system."""
import logging
from .models import EventCategory, ClassifiedEvent, CooldownState, CooldownResult
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

EVENT_COOLDOWN_MAP = {
    EventCategory.CONFLICT: "COOLDOWN_CONFLICT",
    EventCategory.SATISFY: "COOLDOWN_SATISFY",
    EventCategory.REVEAL: "COOLDOWN_REVEAL",
    EventCategory.TWIST: "COOLDOWN_TWIST",
    EventCategory.DAILY: "COOLDOWN_DAILY",
}

EVENT_KEYWORDS = {
    EventCategory.CONFLICT: ["战斗", "冲突", "对峙", "交手", "厮杀", "打斗", "击杀", "搏斗"],
    EventCategory.SATISFY: ["成功", "胜利", "获得", "突破", "晋级", "收获", "如愿"],
    EventCategory.REVEAL: ["真相", "揭露", "发现", "秘密", "揭示", "暴露", "坦白"],
    EventCategory.TWIST: ["反转", "背叛", "突变", "意外", "出乎意料", "竟然", "谁知"],
    EventCategory.DAILY: ["日常", "闲聊", "休息", "修炼", "赶路", "用餐"],
}


class EventMatrix:
    def __init__(self, config: EnhancementConfig, llm_call=None):
        self.config = config
        self.llm_call = llm_call
        self.cooldown_state = CooldownState()

    def classify_events(self, chapter_text: str, chapter_index: int) -> list[ClassifiedEvent]:
        events = []
        for category, keywords in EVENT_KEYWORDS.items():
            for kw in keywords:
                if kw in chapter_text:
                    events.append(ClassifiedEvent(chapter_index=chapter_index, category=category, description=f"检测到'{kw}'"))
                    break
        if not events:
            events.append(ClassifiedEvent(chapter_index=chapter_index, category=EventCategory.DAILY, description="日常情节"))
        return events

    def check_cooldown(self, current_chapter: int, context_tags: list[str] | None = None) -> CooldownResult:
        context_tags = context_tags or []
        is_special_context = any(t in context_tags for t in ["flashback", "memory", "legend"])
        violations = []
        allowed = []
        for category in EventCategory:
            config_key = EVENT_COOLDOWN_MAP.get(category)
            cooldown = getattr(self.config, config_key, 0) if config_key else 0
            last = self.cooldown_state.last_chapter.get(category.value, -999)
            gap = current_chapter - last
            if gap <= cooldown and cooldown > 0:
                if is_special_context:
                    logger.info(f"  特殊上下文覆盖: 允许重复事件类型 {category.value}（{context_tags}）")
                    allowed.append(category)
                else:
                    violations.append(f"{category.value}冷却中(距上次{gap}章,需{cooldown}章)")
            else:
                allowed.append(category)
        return CooldownResult(violations=violations, allowed_categories=allowed)

    def update_cooldown_state(self, events: list[ClassifiedEvent]):
        for e in events:
            self.cooldown_state.last_chapter[e.category.value] = e.chapter_index

    def get_allowed_event_types(self, current_chapter: int) -> list[EventCategory]:
        result = self.check_cooldown(current_chapter)
        return result.allowed_categories

    def generate_event_constraint(self, current_chapter: int) -> str:
        result = self.check_cooldown(current_chapter)
        if not result.violations:
            return ""
        allowed_names = [c.value for c in result.allowed_categories]
        return (
            "\n【事件冷却约束】\n"
            f"以下事件类型处于冷却期: {', '.join(result.violations)}\n"
            f"允许的事件类型: {', '.join(allowed_names) if allowed_names else '日常'}\n"
            "请不要在冷却期内使用被限制的事件类型\n"
        )

    def get_state(self) -> dict:
        return {"cooldown_state": self.cooldown_state.model_dump()}

    def restore_state(self, state: dict):
        if "cooldown_state" in state:
            self.cooldown_state = CooldownState(**state["cooldown_state"])
