"""线程池管理器：将伏笔/悬念/信息差统一为有生命周期的合约对象。

核心思想：伏笔不再是被动的文字描述，而是驱动生成的强制约束。
每个线程有截止日期、urgency 评分、推进日志，系统每章生成前
自动计算 mandate（强制任务）注入 writer prompt。
"""
import logging
import uuid
from .models import (
    StoryThread, StoryThreadStatus, StoryThreadType, ThreadAdvanceLog,
)
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)


class ThreadPool:
    def __init__(self, config: EnhancementConfig):
        self.config = config
        self.threads: list[StoryThread] = []

    # ─── 生命周期管理 ───

    def plant(
        self,
        description: str,
        planted_chapter: int,
        thread_type: str = "伏笔",
        resolution_hint: str = "",
        must_resolve_by: int = 0,
        source: str = "",
        thread_id: str = "",
    ) -> StoryThread:
        """埋入新线程。如果 description 相同且 planted_chapter 相同则去重。"""
        # 去重
        for t in self.threads:
            if t.description == description and t.planted_chapter == planted_chapter:
                return t
        # 尝试映射类型
        try:
            ttype = StoryThreadType(thread_type)
        except ValueError:
            ttype = StoryThreadType.FORESHADOW

        if not must_resolve_by:
            must_resolve_by = planted_chapter + self.config.THREAD_DEFAULT_DEADLINE

        tid = thread_id or f"TH_{uuid.uuid4().hex[:6]}"
        thread = StoryThread(
            thread_id=tid,
            type=ttype,
            status=StoryThreadStatus.ACTIVE,
            planted_chapter=planted_chapter,
            description=description,
            resolution_hint=resolution_hint,
            must_resolve_by=must_resolve_by,
            source=source,
        )
        self.threads.append(thread)
        # 限制活跃线程数
        active = [t for t in self.threads if t.status in (StoryThreadStatus.ACTIVE, StoryThreadStatus.RESOLVING)]
        if len(active) > self.config.THREAD_MAX_ACTIVE:
            # 关闭最旧的
            oldest = sorted(active, key=lambda t: t.planted_chapter)
            for t in oldest[: len(active) - self.config.THREAD_MAX_ACTIVE]:
                t.status = StoryThreadStatus.CLOSED
        logger.info(f"Thread planted: {tid} [{thread_type}] ch{planted_chapter}: {description[:40]}")
        return thread

    def advance(self, thread_id: str, chapter: int, note: str = ""):
        """记录线程在某章的推进。"""
        for t in self.threads:
            if t.thread_id == thread_id:
                if t.status == StoryThreadStatus.CLOSED:
                    return
                t.status = StoryThreadStatus.RESOLVING
                t.advance_log.append(ThreadAdvanceLog(chapter=chapter, note=note or "推进"))
                return

    def close(self, thread_id: str, reason: str = ""):
        """关闭线程。"""
        for t in self.threads:
            if t.thread_id == thread_id:
                t.status = StoryThreadStatus.CLOSED
                if reason:
                    t.advance_log.append(ThreadAdvanceLog(chapter=0, note=f"关闭: {reason}"))
                logger.info(f"Thread closed: {thread_id} — {reason}")
                return

    def close_by_description(self, description: str, chapter: int, reason: str = ""):
        """通过描述匹配关闭线程（用于与 DB foreshadowing 联动）。"""
        for t in self.threads:
            if t.status != StoryThreadStatus.CLOSED and t.description == description:
                t.status = StoryThreadStatus.CLOSED
                if reason:
                    t.advance_log.append(ThreadAdvanceLog(chapter=chapter, note=f"关闭: {reason}"))
                logger.info(f"Thread closed by desc: {t.thread_id} — {reason}")
                return

    # ─── Mandate 生成（核心）───

    def get_mandates(self, current_chapter: int) -> dict:
        """返回三类强制任务：critical（必须关闭）、urgent（必须推进）、optional。"""
        self._update_urgency(current_chapter)
        critical = []
        urgent = []
        optional = []
        for t in self.threads:
            if t.status == StoryThreadStatus.CLOSED:
                continue
            # 已到截止期 → 必须关闭
            if t.must_resolve_by > 0 and current_chapter >= t.must_resolve_by:
                critical.append(t)
            # urgency 超阈值 → 必须推进
            elif t.urgency_score >= self.config.THREAD_URGENCY_THRESHOLD:
                urgent.append(t)
            else:
                optional.append(t)
        # 按 urgency 降序排列
        critical.sort(key=lambda t: -t.urgency_score)
        urgent.sort(key=lambda t: -t.urgency_score)
        return {
            "critical": critical[: self.config.THREAD_MANDATE_CRITICAL_MAX],
            "urgent": urgent[: self.config.THREAD_MANDATE_URGENT_MAX],
            "optional": optional[:5],
        }

    def get_snapshot_text(self, current_chapter: int) -> str:
        """生成给 AI 的线程快照文本（用于 pre-generation context）。"""
        mandates = self.get_mandates(current_chapter)
        lines = ["\n【线程合约 — 本章强制任务】"]

        if mandates["critical"]:
            lines.append("⛔ 必须关闭（已到截止期）：")
            for t in mandates["critical"]:
                hint = f"，回收提示：{t.resolution_hint}" if t.resolution_hint else ""
                lines.append(f"  - {t.thread_id}: 「{t.description}」（已沉默{t.urgency_score}章）{hint}")

        if mandates["urgent"]:
            lines.append("⚠️ 必须推进（已沉默多章）：")
            for t in mandates["urgent"]:
                hint = f"，方向：{t.resolution_hint}" if t.resolution_hint else ""
                lines.append(f"  - {t.thread_id}: 「{t.description}」（已沉默{t.urgency_score}章）{hint}")

        if mandates["optional"]:
            lines.append("✅ 可选推进：")
            for t in mandates["optional"]:
                lines.append(f"  - {t.thread_id}: 「{t.description}」")

        if not (mandates["critical"] or mandates["urgent"] or mandates["optional"]):
            lines.append("（当前无活跃线程）")

        return "\n".join(lines)

    # ─── 健康检查 ───

    def health_check(self) -> list[StoryThread]:
        """返回逾期孤儿线程（超过截止期 5 章仍未关闭）。"""
        orphans = []
        for t in self.threads:
            if t.status == StoryThreadStatus.CLOSED:
                continue
            if t.must_resolve_by > 0 and t.urgency_score > (t.must_resolve_by - t.planted_chapter + 5):
                orphans.append(t)
        return orphans

    def get_active(self) -> list[StoryThread]:
        """返回所有活跃线程。"""
        return [t for t in self.threads if t.status != StoryThreadStatus.CLOSED]

    # ─── 同步 ───

    def sync_from_db(self, db_foreshadowing_items: list):
        """从 DB foreshadowing 表同步未解伏笔到线程池。"""
        existing_descs = {t.description for t in self.threads if t.status != StoryThreadStatus.CLOSED}
        for item in db_foreshadowing_items:
            desc = getattr(item, "description", "")
            if not desc or desc in existing_descs:
                continue
            planted = getattr(item, "planted_chapter", 0) or 0
            close_by = getattr(item, "close_by_chapter", None)
            must_by = int(close_by) if close_by else 0
            self.plant(
                description=desc,
                planted_chapter=planted,
                thread_type="伏笔",
                resolution_hint=getattr(item, "payoff_condition", "") or "",
                must_resolve_by=must_by,
                source="db_foreshadow",
                thread_id=f"DB_{getattr(item, 'id', uuid.uuid4().hex[:6])}",
            )

    def sync_from_ledger(self, ledger: dict):
        """从 open_intents_ledger 同步 unresolved_payoffs 和 continuity_debts。"""
        existing_descs = {t.description for t in self.threads if t.status != StoryThreadStatus.CLOSED}
        # unresolved_payoffs → 悬念/伏笔
        for item in (ledger.get("unresolved_payoffs") or []):
            desc = item.get("description", "")
            if not desc or desc in existing_descs:
                continue
            deadline = int(item.get("deadline_hint", 0) or 0)
            self.plant(
                description=desc,
                planted_chapter=int(item.get("chapter", 0) or 0),
                thread_type="悬念",
                resolution_hint=item.get("resolution_hint", ""),
                must_resolve_by=deadline,
                source="open_intent",
            )
        # continuity_debts → 剧情债务
        for item in (ledger.get("continuity_debts") or []):
            desc = item.get("description", "")
            if not desc or desc in existing_descs:
                continue
            deadline = int(item.get("deadline_hint", 0) or 0)
            self.plant(
                description=desc,
                planted_chapter=int(item.get("chapter", 0) or 0),
                thread_type="剧情债务",
                must_resolve_by=deadline,
                source="open_intent",
            )

    # ─── 内部 ───

    def _update_urgency(self, current_chapter: int):
        """更新所有活跃线程的 urgency_score。"""
        for t in self.threads:
            if t.status == StoryThreadStatus.CLOSED:
                continue
            t.urgency_score = max(0, current_chapter - t.planted_chapter)

    # ─── 持久化 ───

    def get_state(self) -> dict:
        return {"threads": [t.model_dump() for t in self.threads]}

    def restore_state(self, state: dict):
        raw = state.get("threads", [])
        self.threads = []
        for item in raw:
            try:
                self.threads.append(StoryThread(**item))
            except Exception:
                continue
