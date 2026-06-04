"""REQ-P0-001: Deep readback before writing."""
from .models import RetrievedFragment, HierarchicalMemory, ReadbackResult
from .enhancement_config import EnhancementConfig


class ReadbackManager:
    def __init__(self, memory_system, config: EnhancementConfig):
        self.memory = memory_system
        self.config = config
        self._rag_engine = None

    def get_readback_context(self, chapter_index: int, task_id: str, query: str = "") -> ReadbackResult:
        if chapter_index <= 1:
            return ReadbackResult(context_text="", fragment_count=0, total_chars=0, used_rag=False)

        fragments = self._rag_search(task_id, query)
        hierarchical = self._organize_hierarchical_memory(task_id, chapter_index)

        all_texts = []
        seen = set()
        for f in fragments:
            key = f.text[:50]
            if key not in seen:
                seen.add(key)
                all_texts.append(f"[回读·第{f.chapter_index}章] {f.text}")

        for text in hierarchical.milestones:
            all_texts.append(f"[转折点] {text}")
        for text in hierarchical.compressed_summaries:
            all_texts.append(f"[远期摘要] {text}")
        for text in hierarchical.recent_full:
            all_texts.append(f"[近期] {text}")

        context = "\n\n".join(all_texts)
        context = self._truncate_to_limit(context)

        return ReadbackResult(
            context_text=context,
            fragment_count=len(fragments),
            total_chars=len(context),
            used_rag=len(fragments) > 0
        )

    def _rag_search(self, task_id: str, query: str) -> list[RetrievedFragment]:
        try:
            if self._rag_engine is None:
                from rag.rag_engine import RAGEngine
                self._rag_engine = RAGEngine()
            if not query:
                return []
            results = self._rag_engine.search(query, top_k=self.config.READBACK_RAG_TOP_K)
            return [RetrievedFragment(chapter_index=r.get("chapter_index", 0), text=r.get("text", ""), score=r.get("score", 0)) for r in results]
        except Exception:
            return []

    def _organize_hierarchical_memory(self, task_id: str, current_chapter: int) -> HierarchicalMemory:
        if not self.memory:
            return HierarchicalMemory()

        recent = []
        compressed = []
        milestones = []

        try:
            summaries = self.memory.get_all_summaries() if hasattr(self.memory, 'get_all_summaries') else []
        except Exception:
            summaries = []

        for s in summaries:
            ch_idx = s.get("chapter_index", 0) if isinstance(s, dict) else getattr(s, "chapter_index", 0)
            text = s.get("summary", "") if isinstance(s, dict) else getattr(s, "summary", "")
            if not text:
                continue
            if current_chapter - ch_idx <= self.config.READBACK_RECENT_WINDOW:
                recent.append(text)
            elif current_chapter - ch_idx <= self.config.READBACK_COMPRESSED_WINDOW:
                compressed.append(text[:200] if len(text) > 200 else text)
            else:
                milestones.append(text[:100] if len(text) > 100 else text)

        if len(recent) > 5:
            recent = recent[-5:]
        if len(compressed) > 20:
            compressed = compressed[-20:]

        return HierarchicalMemory(recent_full=recent, compressed_summaries=compressed, milestones=milestones)

    def _truncate_to_limit(self, text: str) -> str:
        if len(text) <= self.config.READBACK_MAX_CHARS:
            return text
        return text[:self.config.READBACK_MAX_CHARS]

    def _fallback_recent_chapters(self, task_id: str) -> str:
        if not self.memory:
            return ""
        try:
            summaries = self.memory.get_all_summaries() if hasattr(self.memory, 'get_all_summaries') else []
            recent = summaries[-3:] if summaries else []
            return "\n\n".join(s.get("summary", "") if isinstance(s, dict) else getattr(s, "summary", "") for s in recent)
        except Exception:
            return ""
