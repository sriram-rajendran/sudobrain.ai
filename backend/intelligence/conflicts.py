"""Cross-source conflict detector.

Finds decisions across projects/channels that seem semantically related but
potentially contradictory. Uses vector similarity to shortlist candidate pairs,
then an LLM to verdict whether they actually conflict.

Expensive so runs limited-scope by default.
"""

import logging
from backend.storage.database import get_connection
from backend.storage.chroma_store import _get_collection

logger = logging.getLogger("sudobrain.intelligence.conflicts")


def _pair_candidates(limit: int = 30, threshold: float = 0.70) -> list[tuple[dict, dict, float]]:
    """Find candidate decision pairs via vector similarity."""
    coll = _get_collection()
    if not coll:
        return []

    try:
        res = coll.get(where={"source": "decision"}, limit=500)
    except Exception:
        return []

    ids = res.get("ids", [])
    docs = res.get("documents", [])
    metas = res.get("metadatas", [])

    seen_pairs: set[tuple] = set()
    pairs: list[tuple[dict, dict, float]] = []
    for i, doc_id in enumerate(ids):
        if len(pairs) >= limit:
            break
        try:
            q = coll.query(
                query_texts=[docs[i][:800]],
                n_results=5,
                where={"source": "decision"},
            )
        except Exception:
            continue
        if not q["ids"][0]:
            continue
        for j, nid in enumerate(q["ids"][0]):
            if nid == doc_id:
                continue
            key = tuple(sorted([doc_id, nid]))
            if key in seen_pairs:
                continue
            dist = q["distances"][0][j] if q.get("distances") else 1.0
            score = 1.0 - dist
            if score < threshold or score > 0.98:  # too-high = duplicates, not conflicts
                continue
            seen_pairs.add(key)

            # Find the neighbor's full row
            try:
                nidx = ids.index(nid)
            except ValueError:
                continue
            a = {"id": doc_id, "text": docs[i], "metadata": metas[i]}
            b = {"id": nid, "text": docs[nidx], "metadata": metas[nidx]}
            pairs.append((a, b, score))
    return pairs


def _llm_verdict(a_text: str, b_text: str) -> dict:
    """Ask local reasoning engine whether the two decisions conflict. Returns dict."""
    from backend.ai.local_llm_engine import ask

    prompt = (
        "Two decisions made in different contexts are below. "
        "Determine if they CONTRADICT each other in a meaningful way. "
        "A contradiction means following one decision would break or reverse the other. "
        "Related-but-compatible decisions are NOT contradictions.\n\n"
        f"Decision A: {a_text}\n\nDecision B: {b_text}\n\n"
        "Respond with JSON only: {\"contradicts\": true|false, \"reason\": \"<1 sentence>\"}"
    )
    try:
        r = ask(prompt, max_wait=45)
        # extract JSON
        import json, re
        m = re.search(r"\{.*\}", r, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        logger.debug("LLM verdict failed: %s", e)
    return {"contradicts": False, "reason": "verdict unavailable"}


def compute_conflicts(max_pairs: int = 20, use_llm: bool = True) -> dict:
    pairs = _pair_candidates(limit=max_pairs, threshold=0.70)

    results = []
    for a, b, score in pairs:
        verdict = {"contradicts": None, "reason": "LLM skipped"}
        if use_llm:
            verdict = _llm_verdict(a["text"], b["text"])

        results.append({
            "similarity": round(score, 3),
            "decision_a": {
                "id": a["id"],
                "text": a["text"][:250],
                "made_by": a["metadata"].get("made_by", ""),
                "project": a["metadata"].get("project", ""),
            },
            "decision_b": {
                "id": b["id"],
                "text": b["text"][:250],
                "made_by": b["metadata"].get("made_by", ""),
                "project": b["metadata"].get("project", ""),
            },
            "contradicts": verdict.get("contradicts"),
            "reason": verdict.get("reason", ""),
        })

    confirmed = [r for r in results if r["contradicts"] is True]
    return {
        "candidates_scanned": len(pairs),
        "confirmed_conflicts": len(confirmed),
        "conflicts": confirmed,
        "all_candidates": results,
    }
