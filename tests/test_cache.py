"""测试 core.cache 模块。"""
import time
import pytest

from core.cache import (
    LRUCache,
    CacheManager,
    make_cache_key,
    get_cache,
    reset_cache,
)


class TestLRUCache:
    def test_basic_set_get(self):
        cache = LRUCache(max_size=10)
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_miss(self):
        cache = LRUCache(max_size=10)
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # 触发 a 的访问（移到末尾）
        cache.get("a")
        cache.set("d", 4)  # 应该淘汰 b
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_ttl(self):
        cache = LRUCache(max_size=10, default_ttl=0.1)
        cache.set("k", "v")
        assert cache.get("k") == "v"
        time.sleep(0.2)
        assert cache.get("k") is None

    def test_clear(self):
        cache = LRUCache(max_size=10)
        cache.set("k", "v")
        cache.clear()
        assert cache.get("k") is None

    def test_stats(self):
        cache = LRUCache(max_size=10)
        cache.set("k", "v")
        cache.get("k")  # hit
        cache.get("x")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5


class TestCacheManager:
    def test_named_caches(self):
        reset_cache()
        mgr = get_cache()
        mgr.set("llm_response", "k1", "v1")
        assert mgr.get("llm_response", "k1") == "v1"
        mgr.set("embedding", "k2", "v2")
        assert mgr.get("embedding", "k2") == "v2"

    def test_clear_specific(self):
        reset_cache()
        mgr = get_cache()
        mgr.set("llm_response", "k1", "v1")
        mgr.set("embedding", "k2", "v2")
        mgr.clear("llm_response")
        assert mgr.get("llm_response", "k1") is None
        assert mgr.get("embedding", "k2") == "v2"

    def test_disabled(self):
        reset_cache()
        mgr = get_cache()
        mgr.enabled = False
        mgr.set("llm_response", "k1", "v1")
        assert mgr.get("llm_response", "k1") is None

    def test_stats(self):
        reset_cache()
        mgr = get_cache()
        mgr.set("llm_response", "k1", "v1")
        stats = mgr.stats()
        assert "llm_response" in stats


class TestMakeCacheKey:
    def test_consistency(self):
        key1 = make_cache_key("gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1000)
        key2 = make_cache_key("gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1000)
        assert key1 == key2

    def test_different_content(self):
        key1 = make_cache_key("gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1000)
        key2 = make_cache_key("gpt-4o", [{"role": "user", "content": "bye"}], 0.7, 1000)
        assert key1 != key2

    def test_different_temperature(self):
        key1 = make_cache_key("gpt-4o", [{"role": "user", "content": "hi"}], 0.7, 1000)
        key2 = make_cache_key("gpt-4o", [{"role": "user", "content": "hi"}], 0.9, 1000)
        assert key1 != key2
