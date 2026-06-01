"""Insights & Mirror — analyze patterns across all SudoBrain data."""

from datetime import date, timedelta
from backend.storage.database import get_connection


def get_overview_stats() -> dict:
    """Get high-level stats across the entire knowledge base."""
    conn = get_connection()

    recordings = conn.execute("SELECT COUNT(*) as c FROM recordings WHERE status = 'completed'").fetchone()["c"]
    total_duration = conn.execute("SELECT COALESCE(SUM(duration_seconds), 0) as s FROM recordings").fetchone()["s"]
    action_items = conn.execute("SELECT COUNT(*) as c FROM action_items").fetchone()["c"]
    pending_tasks = conn.execute("SELECT COUNT(*) as c FROM action_items WHERE status = 'pending'").fetchone()["c"]
    completed_tasks = conn.execute("SELECT COUNT(*) as c FROM action_items WHERE status = 'completed'").fetchone()["c"]

    decisions_count = 0
    try:
        decisions_count = conn.execute("SELECT COUNT(*) as c FROM decisions_journal").fetchone()["c"]
    except Exception:
        try:
            decisions_count = conn.execute("SELECT COUNT(*) as c FROM decisions").fetchone()["c"]
        except Exception:
            pass

    people = conn.execute("SELECT COUNT(*) as c FROM people WHERE is_self = FALSE").fetchone()["c"]

    promises_total = 0
    promises_pending = 0
    try:
        promises_total = conn.execute("SELECT COUNT(*) as c FROM promises").fetchone()["c"]
        promises_pending = conn.execute("SELECT COUNT(*) as c FROM promises WHERE status = 'pending'").fetchone()["c"]
    except Exception:
        pass

    rules_count = 0
    try:
        rules_count = conn.execute(
            "SELECT COUNT(*) as c FROM learned_rules WHERE COALESCE(status, CASE WHEN active THEN 'active' ELSE 'inactive' END) = 'active'"
        ).fetchone()["c"]
    except Exception:
        pass

    embeddings = 0
    try:
        embeddings = conn.execute("SELECT COUNT(*) as c FROM embeddings").fetchone()["c"]
    except Exception:
        pass

    conn.close()

    return {
        "recordings": recordings,
        "total_recording_hours": round(total_duration / 3600, 1),
        "action_items": action_items,
        "pending_tasks": pending_tasks,
        "completed_tasks": completed_tasks,
        "task_completion_rate": round(completed_tasks / max(action_items, 1) * 100, 1),
        "decisions": decisions_count,
        "people": people,
        "promises_total": promises_total,
        "promises_pending": promises_pending,
        "promise_fulfillment_rate": round((promises_total - promises_pending) / max(promises_total, 1) * 100, 1),
        "learned_rules": rules_count,
        "embeddings": embeddings,
    }


def get_weekly_activity(weeks_back: int = 4) -> list:
    """Get activity breakdown per week."""
    conn = get_connection()
    result = []

    for w in range(weeks_back):
        end = date.today() - timedelta(weeks=w)
        start = end - timedelta(days=6)

        recordings = conn.execute(
            "SELECT COUNT(*) as c FROM recordings WHERE date(created_at) BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()["c"]

        tasks_created = conn.execute(
            "SELECT COUNT(*) as c FROM action_items WHERE date(created_at) BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()["c"]

        result.append({
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "recordings": recordings,
            "tasks_created": tasks_created,
        })

    conn.close()
    return result


def get_project_health() -> list:
    """Score project health based on task velocity and meeting activity."""
    conn = get_connection()

    # Get unique projects from action items
    projects = conn.execute(
        "SELECT DISTINCT project FROM action_items WHERE project IS NOT NULL AND project != ''"
    ).fetchall()

    result = []
    for p in projects:
        name = p["project"]
        total = conn.execute("SELECT COUNT(*) as c FROM action_items WHERE project = ?", (name,)).fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) as c FROM action_items WHERE project = ? AND status = 'pending'", (name,)).fetchone()["c"]
        completed = conn.execute("SELECT COUNT(*) as c FROM action_items WHERE project = ? AND status = 'completed'", (name,)).fetchone()["c"]

        # Health: more completed = healthier
        completion_rate = completed / max(total, 1) * 100
        if completion_rate > 70:
            health = "healthy"
        elif completion_rate > 40:
            health = "at_risk"
        else:
            health = "stalled"

        result.append({
            "project": name,
            "total_tasks": total,
            "pending": pending,
            "completed": completed,
            "completion_rate": round(completion_rate, 1),
            "health": health,
        })

    conn.close()
    return result


def get_people_interaction_summary() -> list:
    """Get interaction frequency with each person."""
    conn = get_connection()
    people = conn.execute("""
        SELECT p.name, p.total_interactions, p.last_interaction, p.health_score,
            (SELECT COUNT(*) FROM promises WHERE promised_to_name = p.name AND status = 'pending') as pending_promises,
            (SELECT COUNT(*) FROM action_items WHERE assignee = p.name AND status = 'pending') as pending_tasks
        FROM people p WHERE p.is_self = FALSE
        ORDER BY p.total_interactions DESC
    """).fetchall()
    conn.close()
    return [dict(p) for p in people]
