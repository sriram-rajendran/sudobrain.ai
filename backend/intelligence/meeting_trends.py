"""Meeting scoring trends — track effectiveness over time."""

import logging
from datetime import datetime, date, timedelta
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.meeting_trends")


def init_score_table():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meeting_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT UNIQUE,
                overall_score INTEGER,
                decisions_score INTEGER,
                action_items_score INTEGER,
                engagement_score INTEGER,
                duration_minutes REAL,
                meeting_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_date ON meeting_scores(created_at)")
        conn.commit()
    finally:
        conn.close()


def save_score(recording_id: str, scores: dict, duration_seconds: float = 0,
               meeting_type: str = "general"):
    """Save a meeting effectiveness score."""
    init_score_table()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO meeting_scores
            (recording_id, overall_score, decisions_score, action_items_score,
             engagement_score, duration_minutes, meeting_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                scores.get("overall_score", 0),
                scores.get("decisions_score", 0),
                scores.get("action_items_score", 0),
                scores.get("engagement_score", 0),
                round(duration_seconds / 60, 1),
                meeting_type,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_score_trend(days: int = 30) -> dict:
    """Get meeting score trend over the last N days."""
    init_score_table()
    conn = get_connection()
    try:
        threshold = (date.today() - timedelta(days=days)).isoformat()

        scores = conn.execute(
            """SELECT overall_score, decisions_score, action_items_score,
                      engagement_score, duration_minutes, meeting_type, created_at
            FROM meeting_scores WHERE created_at >= ?
            ORDER BY created_at ASC""",
            (threshold,),
        ).fetchall()

        if not scores:
            return {"trend": [], "summary": {}, "period_days": days}

        scores_list = [dict(s) for s in scores]

        # Calculate averages
        avg_overall = sum(s["overall_score"] for s in scores_list) / len(scores_list)
        avg_duration = sum(s["duration_minutes"] or 0 for s in scores_list) / len(scores_list)

        # Compare first half vs second half for trend direction
        mid = len(scores_list) // 2
        if mid > 0:
            first_half_avg = sum(s["overall_score"] for s in scores_list[:mid]) / mid
            second_half_avg = sum(s["overall_score"] for s in scores_list[mid:]) / (len(scores_list) - mid)
            trend_direction = "improving" if second_half_avg > first_half_avg else "declining" if second_half_avg < first_half_avg else "stable"
        else:
            trend_direction = "insufficient_data"

        # By meeting type
        by_type = {}
        for s in scores_list:
            mt = s.get("meeting_type") or "general"
            if mt not in by_type:
                by_type[mt] = {"count": 0, "total_score": 0}
            by_type[mt]["count"] += 1
            by_type[mt]["total_score"] += s["overall_score"]

        for mt in by_type:
            by_type[mt]["avg_score"] = round(by_type[mt]["total_score"] / by_type[mt]["count"])

        return {
            "trend": scores_list,
            "summary": {
                "total_meetings": len(scores_list),
                "avg_score": round(avg_overall),
                "avg_duration_minutes": round(avg_duration, 1),
                "trend_direction": trend_direction,
                "by_type": by_type,
            },
            "period_days": days,
        }
    finally:
        conn.close()


def get_worst_meetings(limit: int = 5) -> list[dict]:
    """Get lowest scoring meetings for reflection."""
    init_score_table()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM meeting_scores ORDER BY overall_score ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
