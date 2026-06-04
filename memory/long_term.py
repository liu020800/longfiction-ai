import numpy as np
import os
import json
import logging
import math
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS not available, using simple cosine similarity")


class LongTermMemory:
    def __init__(self, index_path: str = None, dim: int = 1536):
        self.index_path = index_path or settings.MEMORY_FAISS_INDEX_PATH
        self.dim = dim
        self.metadata: list[dict] = []
        self.current_chapter: int = 0
        self.decay_lambda: float = getattr(settings, 'MEMORY_DECAY_LAMBDA', 0.02)
        self._init_index()

    def _init_index(self):
        if FAISS_AVAILABLE:
            if os.path.exists(self.index_path + ".index"):
                self.index = faiss.read_index(self.index_path + ".index")
                meta_path = self.index_path + ".meta.json"
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as f:
                        self.metadata = json.load(f)
            else:
                self.index = faiss.IndexFlatIP(self.dim)
        else:
            self.vectors: list[np.ndarray] = []

    def add(self, text: str, embedding: np.ndarray, meta: dict = None):
        logger.debug(f"LTM.add: text={text[:60]}..., shape={embedding.shape}, dim={self.dim}")
        if embedding.shape[0] != self.dim:
            logger.info(f"LTM dim change: {self.dim} -> {embedding.shape[0]}")
            self.dim = embedding.shape[0]
            if FAISS_AVAILABLE:
                self.index = faiss.IndexFlatIP(self.dim)
            else:
                self.vectors = []

        meta = meta or {}
        meta["text"] = text
        if "importance" not in meta:
            meta["importance"] = 1.0
        if "created_chapter" not in meta:
            meta["created_chapter"] = self.current_chapter
        if "decay_factor" not in meta:
            meta["decay_factor"] = 1.0
        self.metadata.append(meta)

        if FAISS_AVAILABLE:
            vec = embedding.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(vec)
            self.index.add(vec)
        else:
            norm = np.linalg.norm(embedding)
            if norm > 0:
                self.vectors.append(embedding / norm)
            else:
                self.vectors.append(embedding)

        self._save()

    def set_current_chapter(self, chapter: int):
        self.current_chapter = chapter

    def _compute_decay(self, meta: dict) -> float:
        created = meta.get("created_chapter", self.current_chapter)
        age = max(0, self.current_chapter - created)
        decay_factor = math.exp(-self.decay_lambda * age)
        return decay_factor

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[dict]:
        if not self.metadata:
            return []

        if FAISS_AVAILABLE:
            vec = query_embedding.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(vec)
            search_k = min(top_k * 3, self.index.ntotal)
            scores, indices = self.index.search(vec, max(1, search_k))
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx >= 0 and idx < len(self.metadata):
                    meta = self.metadata[idx]
                    importance = meta.get("importance", 1.0)
                    decay = self._compute_decay(meta)
                    adjusted_score = float(score) * decay * importance
                    result = {**meta, "score": float(score), "adjusted_score": adjusted_score, "decay_factor": decay}
                    results.append(result)
            results.sort(key=lambda x: x["adjusted_score"], reverse=True)
            return results[:top_k]
        else:
            return self._simple_search(query_embedding, top_k)

    def _simple_search(self, query: np.ndarray, top_k: int) -> list[dict]:
        if not self.vectors:
            return []
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm
        scores = [float(np.dot(query, v)) for v in self.vectors]
        top_indices = np.argsort(scores)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            result = {**self.metadata[idx], "score": scores[idx]}
            results.append(result)
        return results

    def _save(self):
        try:
            parent_dir = os.path.dirname(self.index_path) if os.path.dirname(self.index_path) else "."
            os.makedirs(parent_dir, exist_ok=True)
            if FAISS_AVAILABLE:
                index_file = self.index_path + ".index"
                faiss.write_index(self.index, index_file)
                logger.debug(f"FAISS index saved: {index_file} ({self.index.ntotal} vectors)")
            meta_path = self.index_path + ".meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            logger.debug(f"LTM metadata saved: {meta_path} ({len(self.metadata)} entries)")
        except Exception as e:
            logger.error(f"LTM _save() FAILED: {e}", exc_info=True)

    def get_all_texts(self) -> list[str]:
        return [m.get("text", "") for m in self.metadata]

    def clear(self):
        self.metadata = []
        if FAISS_AVAILABLE:
            self.index = faiss.IndexFlatIP(self.dim)
        else:
            self.vectors = []
        for suffix in [".index", ".meta.json"]:
            path = self.index_path + suffix
            if os.path.exists(path):
                os.remove(path)
