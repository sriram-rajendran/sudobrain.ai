"""Stale-decision detector.

Decisions made >N days ago where their referenced project/topic has new activity.
Idea: reality may have shifted since the decision, worth revisiting.

Score:
  - age: days since decision
  - recent_activity: slack mentions of the decision's project in last 14d
  - contradicting_signal: boolean, flagged via semantic similarity between decision
    text and recent messages (if vectors available)

Output: decisions ranked by staleness × activity.
"""

from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection


def compute_stale_decisions(min_age_days: int = 21) -> dict:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, text, made_by, project, created_at
            FROM decisions
            WHERE created_at < ?
              AND project IS NOT NULL AND project != ''
            ORDER BY created_at ASC
            """,
            ((datetime.now(timezone.utc) - timedelta(days=min_age_days)).replace(tzinfo=None),),
        ).fetchall()

        now = datetime.now(timezone.utc)
        result = []
        recent_cutoff = now - timedelta(days=14)

        for r in rows:
            pname = r["project"]
            created = r["created_at"]
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (now - created).days if created else None

            # Recent project activity signal
            chatter = conn.execute(
                """
                SELECT COUNT(*) c FROM slack_messages
                WHERE LOWER(text) LIKE LOWER(?)
                  AND message_at >= ?
                """,
                (f"%{pname}%", recent_cutoff),
            ).fetchone()["c"] or 0

            linear_activity = conn.execute(
                """
                SELECT COUNT(*) c FROM linear_issues
                WHERE project_name = ?
                  AND updated_at >= ?
                """,
                (pname, recent_cutoff),
            ).fetchone()["c"] or 0

            total_activity = chatter + linear_activity
            if total_activity < 3:
                continue  # project went quiet; decision isn't being challenged

            # Staleness score: log-scaled age × activity
            import math
            stale_score = round(math.log10(max(age_days, 1)) * total_activity, 1)

            result.append({
                "decision_id": r["id"],
                "text": r["text"][:200],
                "made_by": r["made_by"] or "unknown",
                "project": pname,
                "age_days": age_days,
                "slack_chatter_14d": chatter,
                "linear_activity_14d": linear_activity,
                "stale_score": stale_score,
            })
    finally:
        conn.close()

    result.sort(key=lambda d: -d["stale_score"])
    return {
        "min_age_days": min_age_days,
        "flagged_count": len(result),
        "flagged": result[:25],
    }
