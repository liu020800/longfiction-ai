"""RRF (Reciprocal Rank Fusion) 融合排序。

将多个检索器的结果融合为一个排序列表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RankedItem:
    """一个已排序的检索项。"""
    doc_id: str
    text: str
    score: float                      # 原始分数（用于显示）
    rank: int                         # 在该检索器中的排名（1-based）
    source: str                       # 来自哪个检索器
    metadata: dict = field(default_factory=dict)

    def __repr__(self):
        return f"RankedItem(doc_id={self.doc_id!r}, source={self.source!r}, rank={self.rank}, score={self.score:.4f})"


def reciprocal_rank_fusion(
    results_per_source: dict[str, list[RankedItem]],
    k: int = 60,
    weights: Optional[dict[str, float]] = None,
    top_n: Optional[int] = None,
) -> list[RankedItem]:
    """Reciprocal Rank Fusion 算法。

    对每个文档，融合分数 = sum(weight[source] / (k + rank[source]))

    Args:
        results_per_source: {source_name: [RankedItem, ...]}，每个 list 已按 rank 升序
        k: RRF 常数（通常 60）
        weights: {source_name: weight}，默认全 1.0
        top_n: 返回前 N 个

    Returns:
        融合后按 RRF 分数降序的 RankedItem 列表（rank 字段被重置为新排名）
    """
    weights = weights or {}
    # 累计 RRF 分数
    rrf_scores: dict[str, float] = {}
    item_map: dict[str, RankedItem] = {}  # doc_id -> 最佳原始 RankedItem
    source_ranks: dict[str, dict[str, int]] = {}  # source -> {doc_id: rank}

    for source, items in results_per_source.items():
        weight = weights.get(source, 1.0)
        source_ranks[source] = {}
        for item in items:
            doc_id = item.doc_id
            rank = item.rank
            source_ranks[source][doc_id] = rank
            rrf_contribution = weight / (k + rank)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + rrf_contribution
            # 保留每个文档的"代表性" RankedItem（取第一次出现的）
            if doc_id not in item_map:
                item_map[doc_id] = item

    # 按 RRF 分数降序
    sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    if top_n is not None:
        sorted_doc_ids = sorted_doc_ids[:top_n]

    # 构造结果
    fused: list[RankedItem] = []
    for new_rank, doc_id in enumerate(sorted_doc_ids, start=1):
        # 使用最佳 RankedItem 作为基础
        best_item = item_map[doc_id]
        # 记录来源信息
        sources = [
            f"{src}(rank={source_ranks[src][doc_id]})"
            for src in results_per_source.keys()
            if doc_id in source_ranks[src]
        ]
        new_metadata = dict(best_item.metadata)
        new_metadata["rrf_sources"] = sources
        new_metadata["rrf_score"] = rrf_scores[doc_id]
        new_metadata["original_score"] = best_item.score
        fused.append(RankedItem(
            doc_id=doc_id,
            text=best_item.text,
            score=rrf_scores[doc_id],  # 用 RRF 分数作为新分数
            rank=new_rank,
            source="+".join(results_per_source.keys()),
            metadata=new_metadata,
        ))
    return fused


def weighted_rrf_fusion(
    *result_lists: list[RankedItem],
    k: int = 60,
    weights: Optional[list[float]] = None,
    top_n: Optional[int] = None,
) -> list[RankedItem]:
    """便捷函数：接收多个已排序的列表。

    Args:
        *result_lists: 多个 RankedItem 列表（每个按 rank 升序）
        k: RRF 常数
        weights: 每个列表的权重
        top_n: 返回前 N 个
    """
    if weights is None:
        weights = [1.0] * len(result_lists)
    sources = {f"s{i}": items for i, items in enumerate(result_lists)}
    w = {f"s{i}": w for i, w in enumerate(weights)}
    return reciprocal_rank_fusion(sources, k=k, weights=w, top_n=top_n)
