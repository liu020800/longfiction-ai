"""LLM Response 缓存层。

基于 prompt hash 的 LRU 缓存，可选 Redis 后端。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目。"""
    key: str
    value: Any
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl: Optional[float] = None  # 秒
    metadata: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self):
        """更新访问时间。"""
        self.last_accessed = time.time()
        self.access_count += 1


def make_cache_key(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    json_mode: bool = False,
    extra: Optional[dict] = None,
) -> str:
    """从 LLM 调用参数生成缓存 key。"""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": round(temperature, 4),
        "max_tokens": max_tokens,
        "json_mode": json_mode,
        "extra": extra or {},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LRUCache:
    """基于内存的 LRU 缓存。"""

    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        # 统计
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值。命中并更新 LRU 顺序。"""
        entry = self._cache.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry.is_expired():
            del self._cache[key]
            self.expirations += 1
            self.misses += 1
            return None
        entry.touch()
        # 移到末尾（最近使用）
        self._cache.move_to_end(key)
        self.hits += 1
        return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        metadata: Optional[dict] = None,
    ):
        """设置缓存值。"""
        if key in self._cache:
            # 已存在，更新
            self._cache[key].value = value
            self._cache[key].touch()
            self._cache.move_to_end(key)
            return
        # 检查容量
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)  # 移除最久未使用
            self.evictions += 1
        # 插入新条目
        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            last_accessed=time.time(),
            ttl=ttl if ttl is not None else self.default_ttl,
            metadata=metadata or {},
        )

    def delete(self, key: str) -> bool:
        """删除缓存条目。"""
        return self._cache.pop(key, None) is not None

    def clear(self):
        """清空缓存。"""
        self._cache.clear()

    def stats(self) -> dict:
        """获取统计信息。"""
        total = self.hits + self.misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total > 0 else 0.0,
            "evictions": self.evictions,
            "expirations": self.expirations,
        }


class CacheManager:
    """缓存管理器。

    提供统一的缓存接口，支持：
    - 不同类型的缓存（LLM response、embedding、风格特征等）
    - TTL 控制
    - 统计信息
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._caches: dict[str, LRUCache] = {}
        self._default_configs: dict[str, dict] = {
            "llm_response": {"max_size": 500, "default_ttl": 3600 * 24},   # 24h
            "llm_json": {"max_size": 500, "default_ttl": 3600 * 24},
            "embedding": {"max_size": 5000, "default_ttl": 3600 * 24 * 7},  # 7d
            "style_feature": {"max_size": 100, "default_ttl": None},         # 永久
        }

    def get_cache(self, name: str) -> LRUCache:
        """获取或创建指定名称的缓存。"""
        if name not in self._caches:
            cfg = self._default_configs.get(name, {"max_size": 100, "default_ttl": 3600})
            self._caches[name] = LRUCache(**cfg)
        return self._caches[name]

    def get(self, name: str, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        return self.get_cache(name).get(key)

    def set(
        self,
        name: str,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ):
        if not self.enabled:
            return
        self.get_cache(name).set(key, value, ttl=ttl)

    def clear(self, name: Optional[str] = None):
        """清空指定或所有缓存。"""
        if name is None:
            for cache in self._caches.values():
                cache.clear()
        elif name in self._caches:
            self._caches[name].clear()

    def stats(self) -> dict:
        """获取所有缓存的统计。"""
        return {name: cache.stats() for name, cache in self._caches.items()}

    def total_stats(self) -> dict:
        """汇总统计。"""
        total_hits = 0
        total_misses = 0
        total_size = 0
        for cache in self._caches.values():
            s = cache.stats()
            total_hits += s["hits"]
            total_misses += s["misses"]
            total_size += s["size"]
        total = total_hits + total_misses
        return {
            "total_size": total_size,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_rate": round(total_hits / total, 3) if total > 0 else 0.0,
            "enabled": self.enabled,
        }


# 全局单例
_cache_manager: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """获取全局缓存管理器。"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(enabled=True)
    return _cache_manager


def reset_cache():
    """重置缓存（用于测试）。"""
    global _cache_manager
    _cache_manager = None


# 装饰器：缓存 LLM 调用
def cached_llm_call(cache_name: str = "llm_response", ttl: Optional[float] = None):
    """装饰器：缓存 LLM 调用结果。

    Usage:
        @cached_llm_call("llm_response", ttl=3600)
        async def call_llm(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            cache = get_cache()
            # 从参数构造 key
            model = kwargs.get("model", "default")
            messages = kwargs.get("messages", [])
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 4096)
            json_mode = kwargs.get("json_mode", False)
            key = make_cache_key(
                model=str(model),
                messages=messages if isinstance(messages, list) else [],
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                json_mode=bool(json_mode),
            )
            cached = cache.get(cache_name, key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_name} key={key[:8]}...")
                return cached
            result = await func(*args, **kwargs)
            cache.set(cache_name, key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
