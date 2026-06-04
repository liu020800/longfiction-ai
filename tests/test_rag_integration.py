"""RAG 2.0 集成测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    print("=== RAG 2.0 集成测试 ===\n")

    # 测试 1: BM25 搜索器
    print("=== Test 1: BM25 搜索器 ===")
    from rag.bm25_searcher import BM25Searcher, simple_chinese_tokenize
    try:
        from rank_bm25 import BM25Okapi
        print("rank_bm25: available")
    except ImportError:
        print("rank_bm25: NOT available, using fallback")

    searcher = BM25Searcher()
    searcher.add_document("ch1", "主角林远获得青云剑法，开始修炼之路")
    searcher.add_document("ch2", "林远与师妹一同下山历练")
    searcher.add_document("ch3", "反派张三阴谋得逞，主角陷入危机")
    searcher.add_document("ch4", "青云宗宗主接见林远，传授心法")
    searcher.add_document("ch5", "林远击败张三，维护了正义")

    queries = [
        "林远",
        "青云剑法",
        "师妹",
        "张三的阴谋",
    ]
    for q in queries:
        results = searcher.search(q, top_k=2)
        print(f"  Query '{q}':")
        for r in results:
            print(f"    - {r.doc_id} (score={r.score:.2f}): {r.text[:50]}")
    print()

    # 测试 2: RRF 融合
    print("=== Test 2: RRF 融合 ===")
    from rag.rrf_fusion import reciprocal_rank_fusion, RankedItem
    items1 = [
        RankedItem(doc_id="a", text="A", score=10, rank=1, source="bm25"),
        RankedItem(doc_id="b", text="B", score=5, rank=2, source="bm25"),
        RankedItem(doc_id="c", text="C", score=3, rank=3, source="bm25"),
    ]
    items2 = [
        RankedItem(doc_id="b", text="B", score=8, rank=1, source="vector"),
        RankedItem(doc_id="a", text="A", score=3, rank=2, source="vector"),
        RankedItem(doc_id="d", text="D", score=1, rank=3, source="vector"),
    ]
    fused = reciprocal_rank_fusion(
        {"bm25": items1, "vector": items2},
        k=60,
    )
    print(f"Fused {len(fused)} results")
    for r in fused:
        sources = r.metadata.get("rrf_sources", [])
        print(f"  Rank {r.rank}: {r.doc_id} (RRF={r.score:.4f}, sources={sources})")
    print()

    # 测试 3: 启发式重排序
    print("=== Test 3: 启发式重排序 ===")
    from rag.reranker import HeuristicReranker
    reranker = HeuristicReranker()
    items = [
        {"doc_id": "1", "text": "林远获得青云剑法，开始修炼，遇到张三", "score": 1.0, "rank": 1, "metadata": {"chapter_index": 5}},
        {"doc_id": "2", "text": "其他内容无关", "score": 0.5, "rank": 2, "metadata": {"chapter_index": 10}},
        {"doc_id": "3", "text": "林远击败张三，维护正义", "score": 0.7, "rank": 3, "metadata": {"chapter_index": 15}},
    ]
    results = reranker.rerank("林远 张三", items, top_n=3)
    print("Reranked results:")
    for r in results:
        print(f"  Rank {r.new_rank}: {r.doc_id} (score={r.score:.4f})")
        print(f"    Breakdown: {r.score_breakdown}")
    print()

    # 测试 4: 完整 RAG 流程模拟
    print("=== Test 4: 完整 RAG 流程 ===")
    # 模拟 RAG 引擎
    query = "林远如何获得青云剑法"
    print(f"Query: {query}")

    # Step 1: BM25 检索
    bm25_results = searcher.search(query, top_k=5)
    bm25_ranked = [
        RankedItem(doc_id=r.doc_id, text=r.text, score=r.score, rank=r.rank, source="bm25")
        for r in bm25_results
    ]
    print(f"  BM25 found: {len(bm25_ranked)} results")

    # Step 2: 模拟向量检索
    vector_ranked = [
        RankedItem(doc_id="ch1", text="主角林远获得青云剑法，开始修炼之路", score=0.9, rank=1, source="vector"),
        RankedItem(doc_id="ch4", text="青云宗宗主接见林远，传授心法", score=0.7, rank=2, source="vector"),
    ]
    print(f"  Vector found: {len(vector_ranked)} results (simulated)")

    # Step 3: RRF 融合
    fused = reciprocal_rank_fusion(
        {"bm25": bm25_ranked, "vector": vector_ranked},
        k=60,
        top_n=5,
    )
    print(f"  Fused: {len(fused)} results")

    # Step 4: 重排序
    rerank_items = [
        {"doc_id": r.doc_id, "text": r.text, "score": r.score, "rank": r.rank, "metadata": r.metadata}
        for r in fused
    ]
    reranked = reranker.rerank(query, rerank_items, top_n=3)
    print(f"  Reranked: {len(reranked)} results")
    for r in reranked:
        print(f"    {r.new_rank}. {r.doc_id}: {r.text[:60]}")

    print("\n=== RAG 2.0 测试完成 ===")


if __name__ == "__main__":
    main()
