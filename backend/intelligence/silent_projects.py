"""Silent project alert — projects with zero recent activity.

For each Linear project:
- last_issue_update: most recent updated_at across all issues
- last_chatter: last slack message mentioning the project
- days_silent: min(days since issue update, days since slack mention)
- stakeholder_count: distinct people currently assigned to open issues

Flags projects silent >= N days, weighted by stakeholder count.
"""

from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection


def compute_silent_projects(threshold_days: int = 14) -> dict:
    conn = get_connection()
    try:
        projects = conn.execute(
            "SELECT id, name FROM linear_projects"
        ).fetchall()

        now = datetime.now(timezone.utc)
        result = []

        for p in projects:
            pname = p["name"]
            # Most recent issue update
            r = conn.execute(
                """
                SELECT MAX(updated_at) AS last_upd,
                       COUNT(*) FILTER (
                           WHERE state_type NOT IN ('completed','cancelled')
                       ) AS open_count,
                       COUNT(DISTINCT assignee_email) FILTER (
                           WHERE state_type NOT IN ('completed','cancelled')
                             AND assignee_email IS NOT NULL
                       ) AS stakeholders
                FROM linear_issues
                WHERE project_name = ?
                """,
                (pname,),
            ).fetchone()

            last_upd = r["last_upd"]
            open_count = r["open_count"] or 0
            stakeholders = r["stakeholders"] or 0

            # Last slack mention
            r2 = conn.execute(
                """
                SELECT MAX(message_at) AS last_msg
                FROM slack_messages
                WHERE LOWER(text) LIKE LOWER(?)
                """,
                (f"%{pname}%",),
            ).fetchone()
            last_chatter = r2["last_msg"]

            # Pick the more-recent of the two as "last activity"
            last_activity = None
            if last_upd and last_chatter:
                last_activity = max(last_upd, last_chatter)
            else:
                last_activity = last_upd or last_chatter

            if not last_activity:
                days_silent = None
            else:
                days_silent = (now - last_activity).days

            if days_silent is None or days_silent < threshold_days:
                continue
            if open_count == 0:  # completed projects aren't "silent"
                continue

            result.append({
                "project": pname,
                "days_silent": days_silent,
                "open_issues": open_count,
                "stakeholders": stakeholders,
                "last_issue_update": last_upd.isoformat() if last_upd else None,
                "last_slack_mention": last_chatter.isoformat() if last_chatter else None,
            })
    finally:
        conn.close()

    result.sort(key=lambda p: (-p["days_silent"], -p["stakeholders"]))

    return {
        "threshold_days": threshold_days,
        "flagged_count": len(result),
        "flagged": result,
    }
