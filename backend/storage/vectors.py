"""Vector embedding store for semantic search using sentence-transformers."""

import numpy as np
from sentence_transformers import SentenceTransformer
from backend.storage.database import get_connection

# Load model once at module level — cached after first load
_model = None

def _get_model():
    global _model
    if _model is None:
        print("[Vectors] Loading embedding model (first time)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("[Vectors] Model loaded")
    return _model


def init_embeddings_table():
    """Create the embeddings table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            tier TEXT DEFAULT 'cold',
            last_accessed DATETIME,
            access_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_table, source_id)
        )
    """)
    conn.commit()
    conn.close()


def embed_text(text: str) -> np.ndarray:
    """Generate embedding for a single text string."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True)


def store_embedding(source_table: str, source_id: int, text: str):
    """Compute and store an embedding for a knowledge item."""
    init_embeddings_table()
    embedding = embed_text(text)
    blob = embedding.astype(np.float32).tobytes()

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO embeddings (source_table, source_id, text, embedding)
        VALUES (?, ?, ?, ?)""",
        (source_table, source_id, text, blob),
    )
    conn.commit()
    conn.close()


def semantic_search(query: str, top_k: int = 10, min_score: float = 0.3) -> list:
    """Search for semantically similar items across the knowledge base.

    Returns list of dicts with: source_table, source_id, text, score.
    """
    init_embeddings_table()
    query_embedding = embed_text(query)

    conn = get_connection()
    rows = conn.execute("SELECT source_table, source_id, text, embedding FROM embeddings").fetchall()
    conn.close()

    if not rows:
        return []

    results = []
    for row in rows:
        stored = np.frombuffer(row["embedding"], dtype=np.float32)
        score = float(np.dot(query_embedding, stored))
        if score >= min_score:
            results.append({
                "source_table": row["source_table"],
                "source_id": row["source_id"],
                "text": row["text"],
                "score": score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def embed_all_segments():
    """Embed all transcript segments that don't have embeddings yet."""
    init_embeddings_table()
    conn = get_connection()

    # Get segments without embeddings
    rows = conn.execute("""
        SELECT s.id, s.text FROM segments s
        WHERE s.id NOT IN (SELECT source_id FROM embeddings WHERE source_table = 'segments')
        AND length(s.text) > 10
    """).fetchall()
    conn.close()

    if not rows:
        print("[Vectors] No new segments to embed")
        return 0

    print(f"[Vectors] Embedding {len(rows)} segments...")
    model = _get_model()
    texts = [r["text"] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    conn = get_connection()
    for i, row in enumerate(rows):
        blob = embeddings[i].astype(np.float32).tobytes()
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (source_table, source_id, text, embedding) VALUES (?, ?, ?, ?)",
            ("segments", row["id"], row["text"], blob),
        )
    conn.commit()
    conn.close()
    print(f"[Vectors] Embedded {len(rows)} segments")
    return len(rows)


def embed_all_action_items():
    """Embed all action items that don't have embeddings yet."""
    init_embeddings_table()
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, text FROM action_items
        WHERE id NOT IN (SELECT source_id FROM embeddings WHERE source_table = 'action_items')
    """).fetchall()
    conn.close()

    if not rows:
        return 0

    print(f"[Vectors] Embedding {len(rows)} action items...")
    model = _get_model()
    texts = [r["text"] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    conn = get_connection()
    for i, row in enumerate(rows):
        blob = embeddings[i].astype(np.float32).tobytes()
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (source_table, source_id, text, embedding) VALUES (?, ?, ?, ?)",
            ("action_items", row["id"], row["text"], blob),
        )
    conn.commit()
    conn.close()
    print(f"[Vectors] Embedded {len(rows)} action items")
    return len(rows)


def embed_all_decisions():
    """Embed all decisions that don't have embeddings yet."""
    init_embeddings_table()
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, text FROM decisions
        WHERE id NOT IN (SELECT source_id FROM embeddings WHERE source_table = 'decisions')
    """).fetchall()
    conn.close()

    if not rows:
        return 0

    print(f"[Vectors] Embedding {len(rows)} decisions...")
    model = _get_model()
    texts = [r["text"] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    conn = get_connection()
    for i, row in enumerate(rows):
        blob = embeddings[i].astype(np.float32).tobytes()
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (source_table, source_id, text, embedding) VALUES (?, ?, ?, ?)",
            ("decisions", row["id"], row["text"], blob),
        )
    conn.commit()
    conn.close()
    print(f"[Vectors] Embedded {len(rows)} decisions")
    return len(rows)


def embed_all():
    """Embed all unembedded items across all tables."""
    total = 0
    total += embed_all_segments()
    total += embed_all_action_items()
    total += embed_all_decisions()
    return total
