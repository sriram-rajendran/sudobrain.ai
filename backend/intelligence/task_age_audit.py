"""Task age audit — flags stale high-priority items.

Surfaces:
1. Linear issues marked Urgent/High but open >30 days (probably not really urgent)
2. Linear issues with due_date passed by N weeks
3. Extracted action_items without any recent related activity

These are the "tasks that have rotted" — either re-triage or close.
"""

from datetime import date, datetime, timedelta, timezone
from backend.storage.database import get_connection


def compute_task_age_audit(threshold_days: int = 30) -> dict:
    conn = get_connection()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)

        # 1. Old urgent Linear issues
        old_urgent = conn.execute(
            """
            SELECT id, title, priority_label, assignee_name, project_name,
                   created_at, updated_at, due_date, url
            FROM linear_issues
            WHERE state_type NOT IN ('completed','cancelled')
              AND priority BETWEEN 1 AND 2
              AND created_at < ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()

        # 2. Heavily overdue (past due by >= 14 days)
        overdue = conn.execute(
            """
            SELECT id, title, priority_label, assignee_name, project_name,
                   due_date, url
            FROM linear_issues
            WHERE state_type NOT IN ('completed','cancelled')
              AND due_date IS NOT NULL
              AND due_date < CURRENT_DATE - INTERVAL '14 days'
            ORDER BY due_date ASC
            """,
        ).fetchall()

        # 3. Stale action items
        action_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=threshold_days)
        stale_actions = conn.execute(
            """
            SELECT id, text, assignee, project, created_at, due_date
            FROM action_items
            WHERE status = 'pending'
              AND created_at < ?
            ORDER BY created_at ASC
            LIMIT 30
            """,
            (action_cutoff,),
        ).fetchall()

    finally:
        conn.close()

    now_d = date.today()

    def issue_to_dict(r):
        age_days = None
        if r["created_at"]:
            created = r["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
        overdue_days = None
        if r["due_date"]:
            overdue_days = (now_d - r["due_date"]).days
        return {
            "id": r["id"],
            "title": r["title"],
            "priority": r["priority_label"],
            "assignee": r["assignee_name"],
            "project": r["project_name"],
            "age_days": age_days,
            "overdue_days": overdue_days,
            "url": r["url"],
        }

    return {
        "threshold_days": threshold_days,
        "old_urgent_count": len(old_urgent),
        "old_urgent": [issue_to_dict(r) for r in old_urgent[:20]],
        "heavily_overdue_count": len(overdue),
        "heavily_overdue": [issue_to_dict(r) for r in overdue[:20]],
        "stale_action_items_count": len(stale_actions),
        "stale_action_items": [
            {
                "id": r["id"],
                "text": (r["text"] or "")[:200],
                "assignee": r["assignee"],
                "project": r["project"],
            }
            for r in stale_actions
        ],
    }
