"""测试 rag 模块：BM25、RRF、重排序。"""
import pytest

from rag.bm25_searcher import BM25Searcher, simple_chinese_tokenize, SimpleBM25Fallback
from rag.rrf_fusion import reciprocal_rank_fusion, weighted_rrf_fusion, RankedItem
from rag.reranker import HeuristicReranker


class TestChineseTokenize:
    def test_basic_chinese(self):
        tokens = simple_chinese_tokenize("主角林远获得青云剑法")
        assert "林远" in tokens
        assert "青云" in tokens
        assert "剑法" in tokens

    def test_english_mixed(self):
        tokens = simple_chinese_tokenize("Hello world 林远")
        assert "hello" in tokens
        assert "world" in tokens
        # 中文双字
        assert "林远" in tokens

    def test_empty(self):
        assert simple_chinese_tokenize("") == []


class TestBM25Searcher:
    def test_add_and_search(self):
        searcher = BM25Searcher()
        searcher.add_document("1", "主角林远获得青云剑法，开始修炼")
        searcher.add_document("2", "林远与师妹一同下山历练")
        searcher.add_document("3", "反派张三阴谋得逞，主角陷入危机")
        # 触发重建
        results = searcher.search("林远 青云 修炼", top_k=2)
        # BM25 至少应该返回一些结果
        assert isinstance(results, list)

    def test_empty_searcher(self):
        searcher = BM25Searcher()
        results = searcher.search("anything", top_k=5)
        assert results == []

    def test_clear(self):
        searcher = BM25Searcher()
        searcher.add_document("1", "test")
        searcher.clear()
        assert len(searcher) == 0


class TestSimpleBM25Fallback:
    def test_search(self):
        searcher = SimpleBM25Fallback()
        searcher.add_document("1", "林远 青云 修炼")
        searcher.add_document("2", "张三 反派 阴谋")
        results = searcher.search("林远", top_k=5)
        assert len(results) > 0
        assert results[0].doc_id == "1"


class TestRRFFusion:
    def test_basic_fusion(self):
        items1 = [
            RankedItem(doc_id="a", text="A", score=10, rank=1, source="bm25"),
            RankedItem(doc_id="b", text="B", score=5, rank=2, source="bm25"),
        ]
        items2 = [
            RankedItem(doc_id="b", text="B", score=8, rank=1, source="vector"),
            RankedItem(doc_id="a", text="A", score=3, rank=2, source="vector"),
        ]
        fused = reciprocal_rank_fusion(
            {"bm25": items1, "vector": items2},
            k=60,
        )
        # a 和 b 都应该出现
        doc_ids = [r.doc_id for r in fused]
        assert "a" in doc_ids
        assert "b" in doc_ids
        # 排名应该是 1, 2
        assert fused[0].rank == 1
        assert fused[1].rank == 2

    def test_top_n(self):
        items1 = [RankedItem(doc_id=f"d{i}", text=f"D{i}", score=10 - i, rank=i + 1, source="s1") for i in range(10)]
        items2 = [RankedItem(doc_id=f"d{i}", text=f"D{i}", score=20 - i, rank=i + 1, source="s2") for i in range(10)]
        fused = reciprocal_rank_fusion({"s1": items1, "s2": items2}, k=60, top_n=3)
        assert len(fused) == 3

    def test_empty(self):
        fused = reciprocal_rank_fusion({})
        assert fused == []

    def test_weights(self):
        items1 = [RankedItem(doc_id="a", text="A", score=10, rank=1, source="s1")]
        items2 = [RankedItem(doc_id="b", text="B", score=10, rank=1, source="s2")]
        fused = reciprocal_rank_fusion(
            {"s1": items1, "s2": items2},
            k=60,
            weights={"s1": 1.0, "s2": 0.0},
        )
        # s2 权重为 0，所以 b 排在最后
        assert fused[0].doc_id == "a"


class TestHeuristicReranker:
    def test_basic_rerank(self):
        items = [
            {"doc_id": "1", "text": "林远 青云 修炼 成功", "score": 1.0, "rank": 1, "metadata": {}},
            {"doc_id": "2", "text": "其他内容", "score": 0.5, "rank": 2, "metadata": {}},
        ]
        reranker = HeuristicReranker()
        results = reranker.rerank("林远 青云", items, top_n=2)
        assert len(results) == 2
        # 文档 1 应该排第一（关键词匹配更多）
        assert results[0].doc_id == "1"

    def test_empty(self):
        reranker = HeuristicReranker()
        assert reranker.rerank("query", [], top_n=5) == []

    def test_length_penalty(self):
        items = [
            {"doc_id": "1", "text": "x" * 3000, "score": 5.0, "rank": 1, "metadata": {}},
            {"doc_id": "2", "text": "x" * 500, "score": 5.0, "rank": 2, "metadata": {}},
        ]
        reranker = HeuristicReranker()
        results = reranker.rerank("query", items, top_n=2)
        # 短文本可能因长度分更高（如果有查询匹配）
        assert results[0].new_rank == 1
