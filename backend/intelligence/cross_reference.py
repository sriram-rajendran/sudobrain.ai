"""Cross-Reference Engine — detect contradictions, stale info, surprising connections."""

import json
from datetime import datetime, date
from backend.storage.database import get_connection
from backend.storage.vectors import semantic_search
from backend.ai.local_llm_engine import ask


def init_cross_ref_tables():
    """Create cross-reference tables."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cross_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            severity TEXT,
            description TEXT NOT NULL,
            source_a_text TEXT,
            source_a_date DATE,
            source_b_text TEXT,
            source_b_date DATE,
            resolution TEXT,
            status TEXT DEFAULT 'open',
            notified BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS recurring_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            mention_count INTEGER DEFAULT 1,
            first_mentioned DATE,
            last_mentioned DATE,
            has_decision BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'unresolved',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def check_contradictions(new_transcript_text: str, transcript_date: str = None) -> list:
    """Check if new transcript contradicts existing knowledge.

    Uses semantic search to find related content, then local reasoning engine to analyze.
    Returns list of detected contradictions.
    """
    init_cross_ref_tables()

    if not new_transcript_text or len(new_transcript_text) < 30:
        return []

    # Find semantically similar existing content
    related = semantic_search(new_transcript_text[:500], top_k=10, min_score=0.3)
    if not related:
        return []

    # Format existing knowledge for local reasoning engine
    existing_items = []
    for r in related:
        existing_items.append(f"[{r['source_table']}] {r['text'][:200]}")

    existing_text = "\n".join(existing_items)

    prompt = f"""Compare the NEW transcript with EXISTING knowledge entries below.
Identify any contradictions, inconsistencies, or conflicts between them.

NEW TRANSCRIPT:
{new_transcript_text[:1000]}

EXISTING KNOWLEDGE:
{existing_text}

If you find contradictions, return JSON:
{{
  "contradictions": [
    {{
      "description": "what contradicts what",
      "severity": "high or medium or low",
      "new_claim": "what the new transcript says",
      "existing_claim": "what existing knowledge says"
    }}
  ],
  "connections": [
    {{
      "description": "surprising connection found",
      "new_text": "relevant new text",
      "existing_text": "relevant existing text"
    }}
  ]
}}

If no contradictions or connections found, return: {{"contradictions": [], "connections": []}}
Return ONLY valid JSON."""

    response = ask(prompt, max_wait=60)

    # Parse response
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    # Save contradictions to database
    findings = []
    conn = get_connection()

    for c in result.get("contradictions", []):
        conn.execute(
            """INSERT INTO cross_references (type, severity, description, source_a_text, source_a_date, source_b_text, source_b_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("contradiction", c.get("severity", "medium"), c.get("description", ""),
             c.get("new_claim", ""), transcript_date or date.today().isoformat(),
             c.get("existing_claim", ""), ""),
        )
        findings.append({"type": "contradiction", **c})

    for c in result.get("connections", []):
        conn.execute(
            """INSERT INTO cross_references (type, severity, description, source_a_text, source_b_text)
            VALUES (?, ?, ?, ?, ?)""",
            ("connection", "low", c.get("description", ""),
             c.get("new_text", ""), c.get("existing_text", "")),
        )
        findings.append({"type": "connection", **c})

    conn.commit()
    conn.close()

    if findings:
        print(f"[CrossRef] Found {len(findings)} items: {[f['type'] for f in findings]}")

    return findings


def track_recurring_topics(topics: list):
    """Track topics mentioned across meetings. Flag if discussed 3+ times without decision."""
    init_cross_ref_tables()
    conn = get_connection()

    for topic_name in topics:
        if not topic_name or len(topic_name) < 3:
            continue

        row = conn.execute(
            "SELECT * FROM recurring_topics WHERE LOWER(topic) = LOWER(?)",
            (topic_name,),
        ).fetchone()

        if row:
            conn.execute(
                """UPDATE recurring_topics SET
                    mention_count = mention_count + 1,
                    last_mentioned = ?
                WHERE id = ?""",
                (date.today().isoformat(), row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO recurring_topics (topic, first_mentioned, last_mentioned) VALUES (?, ?, ?)",
                (topic_name, date.today().isoformat(), date.today().isoformat()),
            )

    conn.commit()
    conn.close()


def get_open_cross_references() -> list:
    """Get all open contradictions and connections."""
    init_cross_ref_tables()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM cross_references WHERE status = 'open' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recurring_unresolved() -> list:
    """Get topics discussed 3+ times without a decision."""
    init_cross_ref_tables()
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM recurring_topics
        WHERE mention_count >= 3 AND has_decision = FALSE AND status = 'unresolved'
        ORDER BY mention_count DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_cross_reference(ref_id: int, resolution: str) -> bool:
    """Resolve a cross-reference finding."""
    init_cross_ref_tables()
    conn = get_connection()
    result = conn.execute(
        "UPDATE cross_references SET status = 'resolved', resolution = ?, resolved_at = ? WHERE id = ?",
        (resolution, datetime.now().isoformat(), ref_id),
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0
