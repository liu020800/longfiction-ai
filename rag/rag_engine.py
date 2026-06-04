import numpy as np
import logging
import asyncio
from memory.long_term import LongTermMemory
from core.llm_router import call_llm, TaskType
from core.config import settings

logger = logging.getLogger(__name__)


class RAGEngine:
    _local_model = None
    _local_model_failed = False

    def __init__(self, long_term_memory: LongTermMemory, bm25_searcher=None, reranker=None):
        self.ltm = long_term_memory
        self.bm25 = bm25_searcher
        self.reranker = reranker
        self._rrf_k = getattr(settings, 'RAG_RRF_K', 60)

    @classmethod
    def _get_local_model(cls):
        """Lazy-load a local sentence-transformers model as embedding fallback."""
        if cls._local_model is not None:
            return cls._local_model
        if cls._local_model_failed:
            return None
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading local embedding model (paraphrase-multilingual-MiniLM-L12-v2) as fallback...")
            cls._local_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            logger.info("Local embedding model loaded successfully")
            return cls._local_model
        except Exception as e:
            logger.warning(f"Failed to load local embedding model: {e}")
            cls._local_model_failed = True
            return None

    async def get_embedding(self, text: str) -> np.ndarray:
        from core.config import settings
        if not settings.LLM_API_KEY or not settings.ENABLE_API_EMBEDDINGS:
            return self._local_embedding_fallback(text)
        try:
            import litellm
            response = await asyncio.wait_for(
                litellm.aembedding(
                    model=settings.EMBEDDING_MODEL,
                    input=text,
                    api_key=settings.LLM_API_KEY,
                    api_base=settings.LLM_API_BASE,
                ),
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            vec = np.array(response.data[0].embedding, dtype=np.float32)
            return vec
        except Exception as e:
            logger.warning(f"API embedding failed ({type(e).__name__}), trying local fallback...")
            return self._local_embedding_fallback(text)

    def _local_embedding_fallback(self, text: str) -> np.ndarray:
        """Use local sentence-transformers model; last resort is random vector."""
        model = self._get_local_model()
        if model is not None:
            try:
                vec = model.encode(text, normalize_embeddings=True)
                return np.array(vec, dtype=np.float32)
            except Exception as e:
                logger.warning(f"Local embedding also failed: {e}")
        logger.warning("All embedding methods failed, using random vector")
        return np.random.randn(self.ltm.dim).astype(np.float32)

    async def index_chapter(self, title: str, content: str, summary: str):
        logger.debug(f"index_chapter: title={title}")
        embedding = await self.get_embedding(f"{title} {summary}")
        self.ltm.add(
            text=f"【{title}】{summary}",
            embedding=embedding,
            meta={"type": "chapter", "title": title, "chapter_id": title}
        )
        if self.bm25 and self.bm25.available:
            try:
                await self.bm25.index_chapter(title, title, content, summary)
            except Exception as e:
                logger.warning(f"BM25 index failed: {e}")

    async def index_event(self, event: str, meta: dict = None):
        embedding = await self.get_embedding(event)
        self.ltm.add(text=event, embedding=embedding, meta=meta or {"type": "event"})

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        has_bm25 = self.bm25 and self.bm25.available
        has_vector = bool(self.ltm.metadata)

        if not has_bm25 and not has_vector:
            return []

        if has_bm25 and has_vector:
            try:
                bm25_results, vector_results = await asyncio.gather(
                    self.bm25.search(query, top_k=top_k * 2),
                    self._vector_search(query, top_k=top_k * 2),
                )
            except Exception as e:
                logger.warning(f"Parallel search failed, falling back: {e}")
                return await self._vector_search(query, top_k)

            from rag.rrf_fusion import rrf_fuse
            fused = rrf_fuse([bm25_results, vector_results], k=self._rrf_k)

            if self.reranker and len(fused) > 1:
                try:
                    fused = await self.reranker.rerank(query, fused, top_k=top_k)
                except Exception as e:
                    logger.warning(f"Reranker failed: {e}")

            seen = set()
            deduped = []
            for r in fused:
                rid = r.get("chapter_id") or r.get("text", "")[:50]
                if rid not in seen:
                    seen.add(rid)
                    deduped.append(r)
            return deduped[:top_k]

        elif has_bm25:
            return await self.bm25.search(query, top_k=top_k)
        else:
            return await self._vector_search(query, top_k)

    async def _vector_search(self, query: str, top_k: int = 5) -> list[dict]:
        query_embedding = await self.get_embedding(query)
        results = self.ltm.search(query_embedding, top_k)
        for r in results:
            r["source"] = "vector"
        return results

    async def retrieve_context_text(self, query: str, top_k: int = 5) -> str:
        results = await self.retrieve(query, top_k)
        if not results:
            return ""
        lines = []
        for r in results:
            score = r.get("score", 0)
            text = r.get("text", "")
            lines.append(f"- [{score:.2f}] {text}")
        return "\n".join(lines)

    async def summarize_for_context(self, query: str, top_k: int = 3) -> str:
        results = await self.retrieve(query, top_k)
        if not results:
            return ""
        context = "\n".join([r.get("text", "") for r in results])
        prompt = f"请将以下历史剧情摘要压缩为关键信息，保留人物、事件、状态变化：\n\n{context}"
        summary = await call_llm(TaskType.PLAN, prompt, temperature=0.3)
        return summary
