import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name: str = "bge-reranker-large", timeout: float = 5.0):
        self.model_name = model_name
        self.timeout = timeout
        self._model = None
        self._available = None

    def _load_model(self):
        if self._available is not None:
            return self._available
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
            self._available = True
            logger.info(f"Reranker model loaded: {self.model_name}")
        except Exception as e:
            logger.warning(f"Reranker model load failed: {e}, skipping rerank")
            self._available = False
        return self._available

    async def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 10,
    ) -> list[dict]:
        if not candidates:
            return []

        if not self._load_model():
            return candidates[:top_k]

        texts = []
        for c in candidates:
            text = c.get("summary", "") or c.get("content", "") or c.get("text", "")
            texts.append(text[:500])

        if not texts:
            return candidates[:top_k]

        try:
            pairs = [(query, t) for t in texts]
            scores = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._model.predict, pairs
                ),
                timeout=self.timeout,
            )
            for i, score in enumerate(scores):
                candidates[i]["rerank_score"] = float(score)
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            return candidates[:top_k]
        except asyncio.TimeoutError:
            logger.warning(f"Reranker timed out after {self.timeout}s, using original order")
            return candidates[:top_k]
        except Exception as e:
            logger.warning(f"Reranker failed: {e}, using original order")
            return candidates[:top_k]
