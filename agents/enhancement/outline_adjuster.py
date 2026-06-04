import logging
import asyncio
import uuid
from datetime import datetime
from .models import OutlineAdjustmentPlan
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

class OutlineAdjuster:
    def __init__(self, config: EnhancementConfig, llm_call=None):
        self.config = config
        self.llm_call = llm_call
        self._pending_plans: list[OutlineAdjustmentPlan] = []
        self._recent_scores: list[float] = []

    def should_trigger_adjustment(self, latest_quality_score: float, deviation_percent: float, overdue_arc_count: int) -> bool:
        self._recent_scores.append(latest_quality_score)
        if len(self._recent_scores) > 10:
            self._recent_scores = self._recent_scores[-10:]

        consecutive_low = 0
        for s in reversed(self._recent_scores):
            if s < self.config.ADJUST_LOW_SCORE_THRESHOLD:
                consecutive_low += 1
            else:
                break

        if consecutive_low >= self.config.ADJUST_CONSECUTIVE_LOW:
            return True
        if deviation_percent > self.config.DEVIATION_THRESHOLD * 100:
            return True
        if overdue_arc_count >= self.config.ADJUST_MAX_OVERDUE_ARCS:
            return True
        return False

    async def generate_adjustment_plan(self, current_outline: list[dict], current_chapter: int, reason: str) -> OutlineAdjustmentPlan:
        plan = OutlineAdjustmentPlan(
            plan_id=str(uuid.uuid4())[:8],
            reason=reason,
            changes=[f"调整第{current_chapter + 1}章及之后的剧情规划"],
            created_at=datetime.now(),
        )
        if self.llm_call:
            try:
                outline_text = "\n".join(f"第{c.get('chapter_index', i)}章: {c.get('title', '')}" for i, c in enumerate(current_outline[current_chapter:]))
                prompt = f"当前大纲（第{current_chapter + 1}章起）：\n{outline_text}\n\n问题：{reason}\n\n请生成调整方案，仅修改当前章节之后的规划，A类锚点（核心剧情节点）不可删除。"
                if asyncio.iscoroutinefunction(self.llm_call):
                    result = await self.llm_call(prompt)
                else:
                    result = self.llm_call(prompt)
                plan.changes.append(result[:500])
            except Exception as e:
                logger.warning(f"大纲调整方案生成失败: {e}")

        self._pending_plans.append(plan)
        return plan

    def apply_adjustment(self, plan_id: str, outline: list[dict]) -> list[dict]:
        for plan in self._pending_plans:
            if plan.plan_id == plan_id:
                plan.confirmed = True
                break
        return outline

    def record_change_log(self, plan: OutlineAdjustmentPlan, confirmed_by: str = "user"):
        logger.info(f"大纲调整{'确认' if plan.confirmed else '驳回'}: plan={plan.plan_id}, reason={plan.reason}, by={confirmed_by}")

    def get_pending_plans(self) -> list[OutlineAdjustmentPlan]:
        return [p for p in self._pending_plans if not p.confirmed]

    def get_state(self) -> dict:
        return {"pending_plans": [p.model_dump() for p in self._pending_plans], "recent_scores": self._recent_scores}

    def restore_state(self, state: dict):
        self._pending_plans = [OutlineAdjustmentPlan(**p) for p in state.get("pending_plans", [])]
        self._recent_scores = state.get("recent_scores", [])
