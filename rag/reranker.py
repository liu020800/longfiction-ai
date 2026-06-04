"""重排序器。

对融合后的检索结果进行精细化重排序。

支持两种模式：
1. LLM 重排序（高质量但慢）
2. 启发式重排序（基于关键词覆盖率、新鲜度等，快）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """重排序结果。"""
    doc_id: str
    text: str
    score: float
    original_rank: int
    new_rank: int
    score_breakdown: dict
    metadata: dict


class HeuristicReranker:
    """基于启发式的重排序。

    考虑因素：
    - 关键词覆盖率
    - 文本长度惩罚（过短/过长都扣分）
    - 章节新鲜度（最新章节加分）
    - 角色/事件相关性
    """

    def __init__(
        self,
        weight_keyword_coverage: float = 0.4,
        weight_length: float = 0.2,
        weight_recency: float = 0.2,
        weight_relevance: float = 0.2,
    ):
        self.weight_keyword_coverage = weight_keyword_coverage
        self.weight_length = weight_length
        self.weight_recency = weight_recency
        self.weight_relevance = weight_relevance

    def rerank(
        self,
        query: str,
        items: list[dict],
        top_n: Optional[int] = None,
    ) -> list[RerankResult]:
        """重排序。

        Args:
            query: 查询文本
            items: 待排序项，每项至少包含 {'doc_id', 'text', 'score', 'rank', 'metadata'}
            top_n: 返回前 N 个

        Returns:
            重排序后的结果
        """
        if not items:
            return []

        # 提取查询关键词
        query_keywords = self._extract_keywords(query)

        scored = []
        for idx, item in enumerate(items):
            text = item.get("text", "")
            doc_id = item.get("doc_id", "")
            original_rank = item.get("rank", idx + 1)
            metadata = item.get("metadata", {})

            # 1. 关键词覆盖率
            coverage = self._keyword_coverage(text, query_keywords)

            # 2. 长度分
            length_score = self._length_score(text)

            # 3. 新鲜度分
            recency = self._recency_score(metadata)

            # 4. 相关性分（来自原始分数）
            original_score = item.get("score", 0.0)
            relevance = self._normalize_score(original_score)

            total = (
                coverage * self.weight_keyword_coverage
                + length_score * self.weight_length
                + recency * self.weight_recency
                + relevance * self.weight_relevance
            )

            breakdown = {
                "keyword_coverage": round(coverage, 4),
                "length_score": round(length_score, 4),
                "recency_score": round(recency, 4),
                "relevance_score": round(relevance, 4),
                "total": round(total, 4),
            }
            scored.append({
                "doc_id": doc_id,
                "text": text,
                "score": total,
                "original_rank": original_rank,
                "metadata": metadata,
                "breakdown": breakdown,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        if top_n is not None:
            scored = scored[:top_n]

        return [
            RerankResult(
                doc_id=s["doc_id"],
                text=s["text"],
                score=s["score"],
                original_rank=s["original_rank"],
                new_rank=new_rank,
                score_breakdown=s["breakdown"],
                metadata=s["metadata"],
            )
            for new_rank, s in enumerate(scored, start=1)
        ]

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """从查询中提取关键词。"""
        if not query:
            return []
        keywords = []
        # 中文 2-gram
        chinese = re.findall(r"[\u4e00-\u9fff]", query)
        for i in range(len(chinese) - 1):
            keywords.append(chinese[i] + chinese[i + 1])
        # 英文/数字
        keywords.extend(re.findall(r"[a-z0-9]+", query.lower()))
        return keywords

    @staticmethod
    def _keyword_coverage(text: str, keywords: list[str]) -> float:
        """计算文本对查询关键词的覆盖率。"""
        if not keywords:
            return 0.0
        if not text:
            return 0.0
        text_lower = text.lower()
        matched = sum(1 for kw in keywords if kw in text_lower)
        return matched / len(keywords)

    @staticmethod
    def _length_score(text: str) -> float:
        """长度评分。理想长度 200-1000 字符。"""
        n = len(text)
        if n < 50:
            return 0.3
        if n < 200:
            return 0.7
        if n <= 1000:
            return 1.0
        if n <= 2000:
            return 0.8
        return 0.5

    @staticmethod
    def _recency_score(metadata: dict) -> float:
        """新鲜度评分。"""
        # 如果有 chapter_index，章节越新分数越高
        ch = metadata.get("chapter_index") or metadata.get("chapter")
        if ch is not None:
            try:
                ch = int(ch)
                # 假设 100 章的小说，第 100 章 = 1.0
                return min(1.0, max(0.0, ch / 100.0))
            except (ValueError, TypeError):
                pass
        return 0.5

    @staticmethod
    def _normalize_score(score: float) -> float:
        """归一化原始分数到 [0, 1]。"""
        # 假设原始分数在 0-50 之间
        return min(1.0, max(0.0, score / 50.0))


class LLMReranker:
    """基于 LLM 的重排序（慢但更准）。"""

    def __init__(self, llm_call):
        self.llm_call = llm_call

    async def rerank(
        self,
        query: str,
        items: list[dict],
        top_n: Optional[int] = None,
    ) -> list[RerankResult]:
        """使用 LLM 重排序。"""
        if not items:
            return []

        # 构造 prompt
        candidates_text = "\n\n".join([
            f"[{i+1}] (id: {item.get('doc_id', '')}) {item.get('text', '')[:300]}"
            for i, item in enumerate(items)
        ])
        prompt = (
            f"请根据与查询的相关度对以下候选文档排序。"
            f"只输出候选编号的列表（按相关性从高到低），用逗号分隔。\n\n"
            f"查询：{query}\n\n"
            f"候选：\n{candidates_text}\n\n"
            f"排序结果（仅输出编号）："
        )
        try:
            response = await self.llm_call(prompt, temperature=0.1, max_tokens=200)
            text = response.strip() if isinstance(response, str) else str(response)
            # 解析编号
            import re as _re
            ids = [int(x) for x in _re.findall(r"\d+", text) if 1 <= int(x) <= len(items)]
            if not ids:
                # 解析失败，回退到原始顺序
                ids = list(range(1, len(items) + 1))
        except Exception as e:
            logger.warning(f"LLM rerank failed: {e}, using original order")
            ids = list(range(1, len(items) + 1))

        results = []
        for new_rank, orig_idx in enumerate(ids, start=1):
            item = items[orig_idx - 1]
            results.append(RerankResult(
                doc_id=item.get("doc_id", ""),
                text=item.get("text", ""),
                score=1.0 / new_rank,  # 用排名倒数作为分数
                original_rank=item.get("rank", orig_idx),
                new_rank=new_rank,
                score_breakdown={"llm_rank": orig_idx},
                metadata=item.get("metadata", {}),
            ))
        if top_n is not None:
            results = results[:top_n]
        return results
