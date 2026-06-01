"""Recurring problem clustering.

Uses ChromaDB vector embeddings to find clusters of semantically-similar items
(Linear issues, action items, Slack messages) that keep recurring — potential
signs of systemic problems or duplicated work.

Approach:
1. Fetch all vectorized docs (titles + brief text)
2. For each doc, find its top-K most similar docs
3. Group docs where mutual similarity > threshold
4. Surface clusters of size ≥3 spanning 2+ sources or 2+ projects
"""

from collections import defaultdict
from backend.storage.chroma_store import _get_collection


def _get_seed_items(source_filter: list[str]) -> list[dict]:
    """Pull ids + metadata from Chroma for the requested source types."""
    coll = _get_collection()
    if not coll:
        return []
    items = []
    for src in source_filter:
        try:
            res = coll.get(where={"source": src}, limit=2000)
        except Exception:
            continue
        for i, doc_id in enumerate(res.get("ids", [])):
            items.append({
                "id": doc_id,
                "text": (res.get("documents") or [])[i] if res.get("documents") else "",
                "metadata": (res.get("metadatas") or [])[i] if res.get("metadatas") else {},
            })
    return items


def compute_recurring_problems(min_cluster_size: int = 3,
                                similarity_threshold: float = 0.75) -> dict:
    coll = _get_collection()
    if not coll:
        return {"error": "ChromaDB unavailable"}

    # Focus on "problem-shaped" content: action items + linear issues + bug-flavored slack
    seeds = _get_seed_items(["action_item", "linear"])
    if not seeds:
        return {"clusters": [], "seeds": 0}

    # Build clusters via greedy agglomeration
    clusters: list[dict] = []
    assigned: set[str] = set()

    for seed in seeds:
        if seed["id"] in assigned or not seed["text"]:
            continue
        try:
            res = coll.query(
                query_texts=[seed["text"][:1500]],
                n_results=10,
                where={"source": {"$in": ["action_item", "linear", "decision"]}},
            )
        except Exception:
            continue

        neighbors = []
        if res and res["ids"] and res["ids"][0]:
            for i, nid in enumerate(res["ids"][0]):
                if nid == seed["id"] or nid in assigned:
                    continue
                dist = res["distances"][0][i] if res.get("distances") else 1.0
                score = 1.0 - dist
                if score < similarity_threshold:
                    continue
                neighbors.append({
                    "id": nid,
                    "score": round(score, 3),
                    "text": res["documents"][0][i][:150] if res.get("documents") else "",
                    "metadata": res["metadatas"][0][i] if res.get("metadatas") else {},
                })

        if len(neighbors) + 1 < min_cluster_size:
            continue

        # Count diversity
        all_metas = [seed["metadata"]] + [n["metadata"] for n in neighbors]
        projects = {m.get("project", "") for m in all_metas if m.get("project")}
        sources = {m.get("source", "") for m in all_metas if m.get("source")}
        assignees = {m.get("assignee", "") for m in all_metas if m.get("assignee")}

        # Only surface clusters that span 2+ projects or 2+ sources
        if len(projects) < 2 and len(sources) < 2:
            continue

        members = [
            {
                "id": seed["id"],
                "text": seed["text"][:150],
                "metadata": seed["metadata"],
                "is_seed": True,
            }
        ] + neighbors

        clusters.append({
            "cluster_size": len(members),
            "diversity": {
                "projects": sorted(projects),
                "sources": sorted(sources),
                "assignees": sorted(assignees),
            },
            "members": members,
        })
        for m in members:
            assigned.add(m["id"])

    clusters.sort(key=lambda c: -c["cluster_size"])
    return {
        "seeds_scanned": len(seeds),
        "cluster_count": len(clusters),
        "clusters": clusters[:15],
    }
