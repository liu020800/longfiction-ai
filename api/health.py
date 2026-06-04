import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def check_health() -> dict:
    checks = {}

    checks["llm"] = await _check_llm()
    checks["database"] = await _check_database()
    checks["vector"] = _check_vector()
    checks["cache"] = _check_cache()
    checks["elasticsearch"] = await _check_elasticsearch()

    all_healthy = all(c.get("status") == "healthy" for c in checks.values())
    any_degraded = any(c.get("status") == "degraded" for c in checks.values())

    overall = "healthy" if all_healthy else ("degraded" if any_degraded else "unhealthy")

    return {
        "status": overall,
        "checks": checks,
    }


async def _check_llm() -> dict:
    try:
        from core.config import settings
        if not settings.LLM_API_KEY:
            return {"status": "degraded", "message": "LLM API key not configured"}
        return {"status": "healthy", "message": "LLM configured"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}


async def _check_database() -> dict:
    try:
        from core.database import get_session
        session = get_session()
        session.execute("SELECT 1")
        session.close()
        return {"status": "healthy", "message": "Database connected"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}


def _check_vector() -> dict:
    try:
        import faiss
        return {"status": "healthy", "message": "FAISS available"}
    except ImportError:
        return {"status": "degraded", "message": "FAISS not available, using numpy fallback"}


def _check_cache() -> dict:
    try:
        from core.config import settings
        if not settings.REDIS_ENABLED or not settings.REDIS_URL:
            return {"status": "degraded", "message": "Redis not enabled (set REDIS_ENABLED=true and REDIS_URL)"}
        from core.cache import get_redis_client
        client = get_redis_client()
        if client:
            return {"status": "healthy", "message": f"Redis connected at {settings.REDIS_URL}"}
        return {"status": "degraded", "message": "Redis configured but connection failed"}
    except Exception as e:
        return {"status": "degraded", "message": str(e)}


async def _check_elasticsearch() -> dict:
    try:
        from core.config import settings
        if not settings.RAG_ES_ENABLED:
            return {"status": "degraded", "message": "Elasticsearch not enabled (set RAG_ES_ENABLED=true)"}
        es_hosts = settings.RAG_ES_HOSTS
        if not es_hosts or es_hosts == "http://localhost:9200":
            return {"status": "degraded", "message": "Elasticsearch not configured (using default)"}
        return {"status": "healthy", "message": f"ES configured at {es_hosts}"}
    except Exception as e:
        return {"status": "degraded", "message": str(e)}
