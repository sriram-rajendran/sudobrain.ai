"""Flag outcome tracking.

Stores every flag the intelligence layer raises (overload, decay, anomaly,
conflict, etc.) and tracks whether the user acted on it, dismissed it,
or ignored it. Over time this yields precision scores per feature.

Schema:
  flag_outcomes(id, feature, flag_key, payload, status, acted_at, outcome_at)

Usage:
  - record_flag(feature, flag_key, payload)   ← intelligence modules call this
  - mark_flag(flag_key, status, outcome)       ← user action
  - compute_self_score()                       ← aggregate per-feature precision
"""

import json
from datetime import datetime, timezone
from backend.storage.database import get_connection


def init_flag_table():
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS flag_outcomes (
                id SERIAL PRIMARY KEY,
                feature TEXT NOT NULL,
                flag_key TEXT NOT NULL,
                payload JSONB,
                status TEXT DEFAULT 'open',
                outcome TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_flag_outcomes_feature ON flag_outcomes(feature);
            CREATE INDEX IF NOT EXISTS idx_flag_outcomes_status ON flag_outcomes(status);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_flag_outcomes_key
                ON flag_outcomes(feature, flag_key);
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_flag(feature: str, flag_key: str, payload: dict | None = None) -> int:
    """Idempotent insert (no-op if same feature+flag_key already exists)."""
    init_flag_table()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO flag_outcomes (feature, flag_key, payload)
            VALUES (?, ?, ?)
            ON CONFLICT (feature, flag_key) DO NOTHING
            """,
            (feature, flag_key, json.dumps(payload or {})),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def mark_flag(flag_key: str, status: str, outcome: str | None = None) -> bool:
    """User marks a flag as acted_on / dismissed / true_positive / false_positive."""
    init_flag_table()
    if status not in {"acted_on", "dismissed", "true_positive", "false_positive", "ignored"}:
        return False
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE flag_outcomes
            SET status = ?, outcome = ?, resolved_at = ?
            WHERE flag_key = ?
            """,
            (status, outcome, datetime.now(timezone.utc), flag_key),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def compute_self_score() -> dict:
    init_flag_table()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT feature,
                   COUNT(*) total,
                   COUNT(*) FILTER (WHERE status = 'true_positive') tp,
                   COUNT(*) FILTER (WHERE status = 'false_positive') fp,
                   COUNT(*) FILTER (WHERE status = 'dismissed') dismissed,
                   COUNT(*) FILTER (WHERE status = 'acted_on') acted,
                   COUNT(*) FILTER (WHERE status = 'open') open
            FROM flag_outcomes
            GROUP BY feature
            """
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r._row)
        judged = (d["tp"] or 0) + (d["fp"] or 0)
        precision = d["tp"] / judged if judged else None
        out.append({
            "feature": d["feature"],
            "total_flags": d["total"],
            "open": d["open"] or 0,
            "acted_on": d["acted"] or 0,
            "dismissed": d["dismissed"] or 0,
            "true_positive": d["tp"] or 0,
            "false_positive": d["fp"] or 0,
            "precision": round(precision, 3) if precision is not None else None,
        })
    return {"features": out}
