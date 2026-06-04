from collections import deque
from typing import Optional
from core.config import settings


class ShortTermMemory:
    def __init__(self, max_chapters: int = None):
        self.max_chapters = max_chapters or settings.MEMORY_SHORT_TERM_SIZE
        self.recent_chapters: deque = deque(maxlen=self.max_chapters)
        self.current_scene_context: list[str] = []

    def add_chapter(self, chapter_title: str, chapter_content: str, summary: str = "", importance_score: float = 1.0):
        self.recent_chapters.append({
            "title": chapter_title,
            "content": chapter_content,
            "summary": summary,
            "importance_score": importance_score,
        })

    def add_scene_context(self, context: str):
        self.current_scene_context.append(context)
        if len(self.current_scene_context) > 10:
            self.current_scene_context = self.current_scene_context[-10:]

    def get_recent_chapters(self) -> list[dict]:
        return list(self.recent_chapters)

    def get_recent_summaries(self) -> str:
        summaries = []
        for ch in self.recent_chapters:
            s = ch.get("summary") or ch.get("content", "")[:500]
            summaries.append(f"【{ch['title']}】{s}")
        return "\n".join(summaries)

    def get_weighted_context(self) -> str:
        if not self.recent_chapters:
            return ""
        parts = []
        for ch in self.recent_chapters:
            score = ch.get("importance_score", 1.0)
            s = ch.get("summary") or ch.get("content", "")[:500]
            prefix = "★★★" if score >= 0.8 else ("★★" if score >= 0.5 else "★")
            parts.append(f"{prefix}【{ch['title']}】{s}")
        return "\n".join(parts)

    def get_scene_context(self) -> str:
        return "\n".join(self.current_scene_context)

    def clear_scene_context(self):
        self.current_scene_context = []

    def clear_chapters(self):
        self.recent_chapters.clear()

    def get_context_for_writer(self) -> str:
        parts = []
        if self.recent_chapters:
            # 只取最近1章摘要，避免与分层摘要系统（hierarchical_summary）重复
            last = list(self.recent_chapters)[-1]
            s = last.get("summary") or last.get("content", "")[:500]
            parts.append(f"## 最近章节摘要\n★★★【{last['title']}】{s}")
        if self.current_scene_context:
            parts.append("## 当前场景上下文\n" + self.get_scene_context())
        return "\n\n".join(parts)
