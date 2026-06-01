"""InsightForge smart search — decomposes questions into sub-queries for richer results.

Instead of a single search, breaks a question into 3-5 targeted sub-queries,
runs each through FTS + semantic search, deduplicates and merges results.
"""

import logging
from typing import Optional

from backend.storage.database import search_transcripts

logger = logging.getLogger("sudobrain.smart_search")


def _generate_sub_queries(question: str) -> list[str]:
    """Decompose a question into sub-queries using reasoning model tier."""
    try:
        from backend.ai.model_router import generate_sub_queries
        queries = generate_sub_queries(question)
        if queries and len(queries) > 1:
            return queries
    except Exception as e:
        logger.debug("Sub-query generation failed: %s", e)

    # Fallback: simple keyword extraction
    import re
    words = re.findall(r'\b\w{4,}\b', question.lower())
    stop = {"what", "when", "where", "which", "that", "this", "have", "been", "with", "about", "from", "does", "will"}
    keywords = [w for w in words if w not in stop]

    queries = [question]
    if len(keywords) >= 2:
        queries.append(" ".join(keywords[:3]))
        queries.append(" ".join(keywords[-3:]))
    return queries


def insight_search(question: str, top_k: int = 15, min_score: float = 0.25) -> dict:
    """Run InsightForge search: decompose → multi-search → merge → rank.

    Returns:
        {
            "sub_queries": [...],
            "results": [...],
            "total_results": int,
        }
    """
    sub_queries = _generate_sub_queries(question)
    logger.info("InsightForge: %d sub-queries for '%s'", len(sub_queries), question[:50])

    seen_texts = set()
    all_results = []

    for sq in sub_queries:
        # FTS search
        fts_results = search_transcripts(sq, limit=5)
        for r in fts_results:
            text = r.get("text", "")
            if text and text not in seen_texts:
                seen_texts.add(text)
                all_results.append({
                    "text": text,
                    "source": f"FTS ({r.get('mode', 'recording')})",
                    "date": r.get("recording_date", ""),
                    "speaker": r.get("speaker_label", ""),
                    "sub_query": sq,
                    "search_type": "fts",
                })

        # Semantic search via ChromaDB
        try:
            from backend.storage.chroma_store import search as chroma_search
            sem_results = chroma_search(sq, top_k=5, min_score=min_score)
            for r in sem_results:
                text = r.get("text", "")
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    meta = r.get("metadata", {})
                    all_results.append({
                        "text": text,
                        "source": f"Semantic ({meta.get('source_table', 'unknown')})",
                        "score": r.get("score", 0),
                        "sub_query": sq,
                        "search_type": "semantic",
                        "metadata": meta,
                    })
        except Exception:
            # Fallback to old vectors module
            try:
                from backend.storage.vectors import semantic_search
                sem_results = semantic_search(sq, top_k=5, min_score=min_score)
                for r in sem_results:
                    text = r.get("text", "")
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_results.append({
                            "text": text,
                            "source": f"Semantic ({r.get('source_table', 'unknown')})",
                            "score": r.get("score", 0),
                            "sub_query": sq,
                            "search_type": "semantic",
                        })
            except Exception:
                pass

    # Sort by score (semantic results) then recency
    all_results.sort(key=lambda x: x.get("score", 0.5), reverse=True)

    return {
        "sub_queries": sub_queries,
        "results": all_results[:top_k],
        "total_results": len(all_results),
    }
