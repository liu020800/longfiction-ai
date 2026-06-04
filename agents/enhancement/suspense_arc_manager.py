import logging
import uuid
from .models import SuspenseArc, ArcLevel
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

class SuspenseArcManager:
    def __init__(self, config: EnhancementConfig):
        self.config = config
        self.arcs: list[SuspenseArc] = []
        self.story_total_chapters: int = 0
    
    def get_active_arcs(self) -> list[SuspenseArc]:
        return [a for a in self.arcs if not a.closed]

    def set_story_horizon(self, total_chapters: int):
        self.story_total_chapters = max(0, int(total_chapters or 0))
        if not self.arcs:
            return
        for arc in self.arcs:
            arc.target_close_chapter = self._bounded_target(arc.level, arc.planted_chapter, arc.target_close_chapter)
            if self.story_total_chapters and arc.target_close_chapter >= self.story_total_chapters:
                arc.target_close_chapter = max(arc.planted_chapter, self.story_total_chapters - 1)
        self.normalize_arcs()

    def _bounded_target(self, level: ArcLevel, chapter_index: int, proposed_target: int | None = None) -> int:
        if level == ArcLevel.SHORT:
            span = self.config.SHORT_ARC_MAX
        elif level == ArcLevel.MEDIUM:
            span = min(self.config.MEDIUM_ARC_MAX, 6)
        else:
            remaining = max(1, self.story_total_chapters - chapter_index - 1) if self.story_total_chapters else 12
            span = max(5, min(12, remaining // 2 if remaining > 10 else remaining))
        target = chapter_index + span if proposed_target is None else proposed_target
        if self.story_total_chapters:
            target = min(target, self.story_total_chapters - 1)
        return max(chapter_index, target)

    def normalize_arcs(self, keep_limit: int = 12):
        if not self.arcs:
            return
        deduped: list[SuspenseArc] = []
        seen: set[tuple[str, str, int]] = set()
        for arc in sorted(self.arcs, key=lambda a: (a.planted_chapter, a.target_close_chapter, a.arc_id)):
            desc_key = (arc.description or "").strip()[:80]
            key = (arc.level.value, desc_key, arc.planted_chapter)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(arc)
        active = [a for a in deduped if not a.closed]
        closed = [a for a in deduped if a.closed]
        if len(active) > keep_limit:
            active.sort(key=lambda a: (a.overdue, a.current_chapter, a.target_close_chapter), reverse=True)
            for arc in active[keep_limit:]:
                arc.closed = True
                closed.append(arc)
            active = active[:keep_limit]
        self.arcs = sorted(active + closed, key=lambda a: (a.closed, a.planted_chapter, a.target_close_chapter))
    
    def generate_arc_instruction(self, chapter_index: int) -> str:
        active = self.get_active_arcs()
        if not active:
            return ""
        instructions = ["\n【悬念弧推进要求】"]
        for arc in active:
            status = "逾期!" if arc.overdue else ""
            instructions.append(f"- [{arc.level.value}弧·{status}]{arc.description}（第{arc.planted_chapter}章埋设，目标第{arc.target_close_chapter}章闭合）")
        instructions.append("本章至少推进1条悬念弧的进展")
        return "\n".join(instructions) + "\n"
    
    def update_after_chapter(self, chapter_text: str, chapter_index: int):
        for arc in self.arcs:
            if arc.closed:
                continue
            arc.current_chapter = chapter_index
            if chapter_index > arc.target_close_chapter:
                arc.overdue = True
        
        self.check_min_active_arcs(chapter_index)
        self._auto_detect_closures(chapter_text, chapter_index)
        self.normalize_arcs()
    
    def check_min_active_arcs(self, chapter_index: int) -> list[SuspenseArc]:
        active = self.get_active_arcs()
        while len(active) < self.config.MIN_ACTIVE_ARCS:
            has_short = any(a.level == ArcLevel.SHORT and not a.closed for a in self.arcs)
            has_medium = any(a.level == ArcLevel.MEDIUM and not a.closed for a in self.arcs)
            has_long = any(a.level == ArcLevel.LONG and not a.closed for a in self.arcs)
            if not has_short:
                new = self.create_new_arc(ArcLevel.SHORT, chapter_index, f"短期悬念(第{chapter_index}章)")
                active.append(new)
            elif not has_medium:
                new = self.create_new_arc(ArcLevel.MEDIUM, chapter_index, f"中期悬念(第{chapter_index}章)")
                active.append(new)
            elif not has_long:
                new = self.create_new_arc(ArcLevel.LONG, chapter_index, f"长线悬念(第{chapter_index}章)")
                active.append(new)
            else:
                break
        return active

    def create_new_arc(self, level: ArcLevel, chapter_index: int, description: str = "") -> SuspenseArc:
        target = self._bounded_target(level, chapter_index)
        arc = SuspenseArc(
            arc_id=str(uuid.uuid4())[:8],
            level=level,
            description=description or f"{level.value}悬念弧",
            planted_chapter=chapter_index,
            target_close_chapter=target,
            current_chapter=chapter_index,
        )
        self.arcs.append(arc)
        return arc
    
    def force_close_overdue_arc(self, arc: SuspenseArc):
        arc.closed = True
        arc.overdue = True
        logger.warning(f"强制闭合逾期悬念弧: {arc.arc_id} ({arc.description})")

    def settle_at_story_end(self, chapter_index: int, reason: str = "故事完结，终局结算"):
        for arc in self.arcs:
            if arc.closed:
                continue
            arc.closed = True
            arc.overdue = False
            arc.current_chapter = chapter_index
            arc.resolved_chapter = chapter_index
            arc.resolved_reason = reason
    
    def _auto_detect_closures(self, chapter_text: str, chapter_index: int):
        closure_keywords = ["真相大白", "终于明白", "原来如此", "恍然大悟", "水落石出", "证实", "揭开", "承认", "找到了", "暴露了",
                           "真相", "原来", "发现", "揭穿", "坦白", "领悟", "明白", "水落石出", "大白", "解开", "谜底"]
        # Phase 1: keyword-based closure for arcs near target
        for kw in closure_keywords:
            if kw in chapter_text:
                for arc in self.get_active_arcs():
                    if chapter_index >= arc.target_close_chapter - 2:
                        arc.closed = True
                        arc.resolved_chapter = chapter_index
                        arc.resolved_reason = f"命中闭合关键词：{kw}"
                        break
                break
        # Phase 2: force-close arcs that are significantly overdue (>5 chapters past target)
        for arc in self.get_active_arcs():
            if arc.target_close_chapter > 0 and chapter_index > arc.target_close_chapter + 5:
                arc.closed = True
                arc.resolved_chapter = chapter_index
                arc.resolved_reason = f"逾期强制闭合（目标ch{arc.target_close_chapter}，当前ch{chapter_index}）"
                logger.info(f"Force-closed overdue arc: {arc.arc_id} ({arc.description[:40]})")
    
    def get_state(self) -> dict:
        return {"suspense_arcs": [a.model_dump() for a in self.arcs]}
    
    def restore_state(self, state: dict):
        self.arcs = [SuspenseArc(**a) for a in state.get("suspense_arcs", [])]
        self.normalize_arcs()

    def get_overdue_alerts(self, current_chapter: int, overdue_threshold: int = 10) -> list[dict]:
        alerts = []
        for arc in self.arcs:
            if arc.closed:
                continue
            if current_chapter > arc.target_close_chapter:
                arc.overdue = True
                overdue_by = current_chapter - arc.target_close_chapter
                alerts.append({
                    "arc_id": arc.arc_id,
                    "description": arc.description,
                    "planted_chapter": arc.planted_chapter,
                    "target_close_chapter": arc.target_close_chapter,
                    "overdue_by": overdue_by,
                    "severity": "critical" if overdue_by > overdue_threshold else "warning",
                    "message": f"伏笔「{arc.description}」已逾期{overdue_by}章未回收，建议近期安排回收",
                })
        return alerts

    def check_suspense_distribution(self, chapter_index: int, window: int = 5) -> str | None:
        chapters_since_hook = 0
        for arc in self.arcs:
            if arc.planted_chapter > chapter_index - window:
                return None
        active = self.get_active_arcs()
        if active:
            return None
        return (
            f"【强制悬念注入】连续{window}章未设置悬念钩子，"
            f"本章必须引入新的悬念或冲突转折点，制造读者好奇心。"
            f"建议：1)引入新谜题 2)角色面临意外选择 3)揭示部分真相留下更多疑问"
        )
