"""ChromaDB vector store — replaces numpy-based similarity search.

Persistent, fast, supports metadata filtering (by date, person, project).
Falls back to the old vectors.py if ChromaDB is unavailable.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("sudobrain.chroma")

_DATA_DIR = os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain"))
CHROMA_DIR = os.path.join(_DATA_DIR, "chroma_db")

_client = None
_collection = None


from chromadb.api.types import EmbeddingFunction, Documents, Embeddings


class _OllamaEmbedder(EmbeddingFunction[Documents]):
    """Chroma EmbeddingFunction using local Ollama nomic-embed-text."""

    def __init__(self, model: str = "nomic-embed-text",
                 url: str = "http://localhost:11434"):
        self.model = model
        self.url = url

    @staticmethod
    def name() -> str:
        return "ollama_nomic_embed_text"

    def __call__(self, input: Documents) -> Embeddings:
        if isinstance(input, str):
            input = [input]
        # Truncate each doc to ~2000 chars to stay within nomic-embed-text's
        # 8192-token context and keep request size reasonable.
        texts = [(t or "")[:2000] if t else " " for t in input]
        # Call one at a time to avoid 400 on large batches (ollama quirk)
        import requests
        embeds = []
        for t in texts:
            r = requests.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": t},
                timeout=60,
            )
            r.raise_for_status()
            embeds.extend(r.json()["embeddings"])
        return embeds

    @staticmethod
    def build_from_config(config):
        return _OllamaEmbedder()

    def get_config(self):
        return {"model": self.model, "url": self.url}


def _get_collection():
    """Get or create the ChromaDB collection (singleton)."""
    global _client, _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = _client.get_or_create_collection(
            name="sudobrain_knowledge",
            metadata={"hnsw:space": "cosine"},
            embedding_function=_OllamaEmbedder(),
        )
        logger.info("ChromaDB initialized at %s (%d items)", CHROMA_DIR, _collection.count())
        return _collection
    except Exception as e:
        logger.warning("ChromaDB not available: %s", e)
        return None


def is_available() -> bool:
    return _get_collection() is not None


def add(doc_id: str, text: str, metadata: dict = None):
    """Add a document to the vector store."""
    coll = _get_collection()
    if not coll or not text or len(text.strip()) < 5:
        return
    meta = metadata or {"_placeholder": 1}
    coll.upsert(ids=[doc_id], documents=[text], metadatas=[meta])


def add_batch(items: list[dict]):
    """Add multiple documents. Each dict needs: id, text, metadata."""
    coll = _get_collection()
    if not coll or not items:
        return
    ids = [str(item["id"]) for item in items]
    texts = [item["text"] for item in items]
    metas = [item.get("metadata", {}) for item in items]
    coll.upsert(ids=ids, documents=texts, metadatas=metas)
    logger.info("ChromaDB: added %d items", len(items))


def search(query: str, top_k: int = 10, min_score: float = 0.3,
           where: dict = None) -> list[dict]:
    """Semantic search with optional metadata filtering.

    Args:
        query: Search query text
        top_k: Max results
        min_score: Minimum similarity (0-1, cosine)
        where: ChromaDB metadata filter, e.g. {"source_table": "segments"}
    """
    coll = _get_collection()
    if not coll:
        return []

    kwargs = {"query_texts": [query], "n_results": top_k}
    if where:
        kwargs["where"] = where

    try:
        results = coll.query(**kwargs)
    except Exception as e:
        logger.warning("ChromaDB search failed: %s", e)
        return []

    items = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results.get("distances") else 1.0
            score = 1.0 - distance  # cosine distance to similarity
            if score < min_score:
                continue
            items.append({
                "id": doc_id,
                "text": results["documents"][0][i] if results.get("documents") else "",
                "score": round(score, 3),
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
            })

    return items


def sync_from_sqlite():
    """Sync all unindexed items from SQLite into ChromaDB."""
    coll = _get_collection()
    if not coll:
        return 0

    from backend.storage.database import get_connection
    conn = get_connection()
    total = 0

    try:
        # Segments
        rows = conn.execute(
            "SELECT id, text, speaker_label, transcript_id FROM segments WHERE length(text) > 10"
        ).fetchall()
        existing = set(coll.get(where={"source_table": "segments"})["ids"]) if coll.count() > 0 else set()
        batch = []
        for r in rows:
            doc_id = f"seg_{r['id']}"
            if doc_id not in existing:
                batch.append({"id": doc_id, "text": r["text"], "metadata": {
                    "source_table": "segments", "source_id": r["id"],
                    "speaker": r["speaker_label"] or "", "transcript_id": r["transcript_id"] or "",
                }})
        if batch:
            add_batch(batch)
            total += len(batch)

        # Action items
        rows = conn.execute("SELECT id, text, assignee, project, status FROM action_items").fetchall()
        batch = []
        for r in rows:
            doc_id = f"action_{r['id']}"
            batch.append({"id": doc_id, "text": r["text"], "metadata": {
                "source_table": "action_items", "source_id": r["id"],
                "assignee": r["assignee"] or "", "project": r["project"] or "",
                "status": r["status"] or "",
            }})
        if batch:
            add_batch(batch)
            total += len(batch)

        # Decisions
        rows = conn.execute("SELECT id, text, made_by, project FROM decisions").fetchall()
        batch = []
        for r in rows:
            doc_id = f"dec_{r['id']}"
            batch.append({"id": doc_id, "text": r["text"], "metadata": {
                "source_table": "decisions", "source_id": r["id"],
                "made_by": r["made_by"] or "", "project": r["project"] or "",
            }})
        if batch:
            add_batch(batch)
            total += len(batch)

        # Promises
        try:
            rows = conn.execute("SELECT id, description, promised_by_name, promised_to_name FROM promises").fetchall()
            batch = []
            for r in rows:
                doc_id = f"prom_{r['id']}"
                batch.append({"id": doc_id, "text": r["description"], "metadata": {
                    "source_table": "promises", "source_id": r["id"],
                    "promised_by": r["promised_by_name"] or "",
                    "promised_to": r["promised_to_name"] or "",
                }})
            if batch:
                add_batch(batch)
                total += len(batch)
        except Exception:
            pass

    finally:
        conn.close()

    logger.info("ChromaDB sync: %d items indexed", total)
    return total


def count() -> int:
    coll = _get_collection()
    return coll.count() if coll else 0
