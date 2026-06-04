import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BM25Searcher:
    def __init__(self, es_client=None, index_name: str = "longfiction"):
        self.es_client = es_client
        self.index_name = index_name
        self.available = es_client is not None

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        if not self.available or not self.es_client:
            return []
        try:
            body = {
                "size": top_k,
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^2", "content", "summary^1.5"],
                        "type": "best_fields",
                    }
                },
            }
            resp = await self.es_client.search(index=self.index_name, body=body)
            results = []
            for hit in resp.get("hits", {}).get("hits", []):
                source = hit["_source"]
                results.append({
                    "chapter_id": source.get("chapter_id", ""),
                    "title": source.get("title", ""),
                    "content": source.get("content", ""),
                    "summary": source.get("summary", ""),
                    "score": hit["_score"],
                    "source": "bm25",
                })
            return results
        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")
            self.available = False
            return []

    async def index_chapter(self, chapter_id: str, title: str, content: str, summary: str = ""):
        if not self.available or not self.es_client:
            return
        try:
            doc = {
                "chapter_id": chapter_id,
                "title": title,
                "content": content,
                "summary": summary,
            }
            await self.es_client.index(index=self.index_name, id=chapter_id, body=doc)
        except Exception as e:
            logger.warning(f"BM25 index chapter failed: {e}")
            self.available = False

    async def delete_chapter(self, chapter_id: str):
        if not self.available or not self.es_client:
            return
        try:
            await self.es_client.delete(index=self.index_name, id=chapter_id)
        except Exception as e:
            logger.warning(f"BM25 delete chapter failed: {e}")
