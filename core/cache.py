import json
import logging
import hashlib
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL or not settings.REDIS_ENABLED:
        return None
    try:
        import redis
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_client.ping()
        logger.info(f"Redis connected: {settings.REDIS_URL}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        _redis_client = None
        return None


def _cache_key(prefix: str, content: str) -> str:
    h = hashlib.md5(content.encode("utf-8")).hexdigest()
    return f"lf:{prefix}:{h}"


def cache_get(prefix: str, key_content: str) -> Optional[str]:
    client = get_redis_client()
    if not client:
        return None
    try:
        return client.get(_cache_key(prefix, key_content))
    except Exception:
        return None


def cache_set(prefix: str, key_content: str, value: str, ttl: int = None):
    client = get_redis_client()
    if not client:
        return
    try:
        client.setex(
            _cache_key(prefix, key_content),
            ttl or settings.REDIS_CACHE_TTL,
            value,
        )
    except Exception as e:
        logger.debug(f"Redis cache set failed: {e}")


def cache_json_get(prefix: str, key_content: str):
    raw = cache_get(prefix, key_content)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def cache_json_set(prefix: str, key_content: str, value, ttl: int = None):
    try:
        cache_set(prefix, key_content, json.dumps(value, ensure_ascii=False), ttl)
    except (TypeError, ValueError):
        pass
