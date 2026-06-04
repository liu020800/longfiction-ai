"""BM25 关键词检索器。

使用 rank_bm25 实现基于关键词权重的检索。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 延迟导入 rank_bm25，避免在没安装时影响其他模块
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    BM25Okapi = None
    logger.warning("rank_bm25 not installed, BM25 search will be disabled")


# 中文分词：简单的 n-gram + 停用词
STOPWORDS = set([
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "吗", "吧", "呢", "啊", "哦", "嗯", "他", "她", "它", "们",
    "把", "被", "对", "从", "向", "为", "以", "于", "及", "或", "与", "而", "等",
])


def simple_chinese_tokenize(text: str) -> list[str]:
    """简单中文分词（双字 n-gram + 单词）。

    优点：不依赖外部分词库
    缺点：精度有限，但足以作为 BM25 关键词检索
    """
    if not text:
        return []
    text = text.lower()
    # 提取中文字符
    tokens = []
    # 英文/数字单词
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)
    # 中文：双字 n-gram
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    # 单字
    for ch in chinese_chars:
        if ch not in STOPWORDS and len(ch.strip()) > 0:
            tokens.append(ch)
    # 双字
    for i in range(len(chinese_chars) - 1):
        bigram = chinese_chars[i] + chinese_chars[i + 1]
        if not all(c in STOPWORDS for c in bigram):
            tokens.append(bigram)
    return tokens


@dataclass
class BM25Document:
    """BM25 文档。"""
    doc_id: str
    text: str
    tokens: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class BM25Result:
    """BM25 检索结果。"""
    doc_id: str
    text: str
    score: float
    rank: int
    metadata: dict = field(default_factory=dict)


class BM25Searcher:
    """BM25 检索器。

    使用 BM25Okapi 算法，支持：
    - 中文分词
    - 增量添加文档
    - 重建索引
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[BM25Document] = []
        self._index: Optional[object] = None  # BM25Okapi 实例
        self._dirty = True

    @property
    def is_empty(self) -> bool:
        return len(self._docs) == 0

    def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ):
        """添加单个文档。"""
        tokens = simple_chinese_tokenize(text)
        self._docs.append(BM25Document(
            doc_id=doc_id,
            text=text,
            tokens=tokens,
            metadata=metadata or {},
        ))
        self._dirty = True

    def add_documents(self, docs: list[tuple[str, str, Optional[dict]]]):
        """批量添加文档。每个元素为 (doc_id, text, metadata)。"""
        for doc_id, text, metadata in docs:
            self.add_document(doc_id, text, metadata)

    def clear(self):
        """清空索引。"""
        self._docs.clear()
        self._index = None
        self._dirty = True

    def _rebuild(self):
        """重建 BM25 索引。"""
        if not HAS_BM25:
            logger.warning("Cannot rebuild: rank_bm25 not installed")
            return
        if not self._docs:
            self._index = None
            self._dirty = False
            return
        corpus = [doc.tokens for doc in self._docs]
        try:
            self._index = BM25Okapi(corpus, k1=self.k1, b=self.b)
            self._dirty = False
        except Exception as e:
            logger.error(f"Failed to build BM25 index: {e}")
            self._index = None

    def search(self, query: str, top_k: int = 10) -> list[BM25Result]:
        """检索。

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            按 score 降序排列的结果列表
        """
        if not HAS_BM25:
            logger.warning("BM25 search unavailable: rank_bm25 not installed")
            return []
        if self._dirty:
            self._rebuild()
        if self._index is None or self.is_empty:
            return []

        query_tokens = simple_chinese_tokenize(query)
        if not query_tokens:
            return []

        try:
            scores = self._index.get_scores(query_tokens)
        except Exception as e:
            logger.error(f"BM25 search error: {e}")
            return []

        # 排序：取 top_k
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for rank, (idx, score) in enumerate(indexed_scores[:top_k], start=1):
            if score <= 0:
                break
            doc = self._docs[idx]
            results.append(BM25Result(
                doc_id=doc.doc_id,
                text=doc.text,
                score=float(score),
                rank=rank,
                metadata=doc.metadata,
            ))
        return results

    def __len__(self) -> int:
        return len(self._docs)


# 简单的内存实现作为 fallback（不依赖 rank_bm25）
class SimpleBM25Fallback:
    """极简的 TF-IDF 风格检索（fallback）。"""
    def __init__(self):
        self._docs: list[tuple[str, str, list[str], dict]] = []
        self._idf: dict[str, float] = {}

    def add_document(self, doc_id: str, text: str, metadata: Optional[dict] = None):
        tokens = simple_chinese_tokenize(text)
        self._docs.append((doc_id, text, tokens, metadata or {}))

    def search(self, query: str, top_k: int = 10) -> list[BM25Result]:
        if not self._docs:
            return []
        query_tokens = simple_chinese_tokenize(query)
        if not query_tokens:
            return []
        # 简单 TF-IDF
        scores = []
        for doc_id, text, tokens, metadata in self._docs:
            score = 0.0
            for qt in query_tokens:
                tf = tokens.count(qt)
                if tf > 0:
                    score += (1 + (tf / max(len(tokens), 1)))
            scores.append((score, doc_id, text, metadata))
        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (score, doc_id, text, metadata) in enumerate(scores[:top_k], start=1):
            if score <= 0:
                break
            results.append(BM25Result(
                doc_id=doc_id, text=text, score=score, rank=rank, metadata=metadata,
            ))
        return results
