import logging

logger = logging.getLogger(__name__)


def rrf_fuse(
    result_sets: list[list[dict]],
    k: int = 60,
    id_field: str = "chapter_id",
) -> list[dict]:
    if not result_sets:
        return []

    id_to_result = {}
    id_to_rrf_scores = {}

    for result_set in result_sets:
        for rank, result in enumerate(result_set):
            doc_id = result.get(id_field, "")
            if not doc_id:
                doc_id = result.get("text", "")[:50]
            rrf_score = 1.0 / (k + rank + 1)

            if doc_id not in id_to_rrf_scores:
                id_to_rrf_scores[doc_id] = 0.0
                id_to_result[doc_id] = result
            id_to_rrf_scores[doc_id] += rrf_score

            if result.get("score", 0) > id_to_result[doc_id].get("score", 0):
                merged = {**result}
                merged["rrf_score"] = id_to_rrf_scores[doc_id]
                id_to_result[doc_id] = merged

    sorted_ids = sorted(id_to_rrf_scores.keys(), key=lambda x: id_to_rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids:
        result = id_to_result[doc_id]
        result["rrf_score"] = id_to_rrf_scores[doc_id]
        results.append(result)

    return results
