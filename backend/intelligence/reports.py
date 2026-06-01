"""Weekly/Monthly intelligence reports — auto-generated personal analytics."""

import logging
from datetime import datetime, date, timedelta
from backend.storage.database import get_connection
from backend.ai.local_llm_engine import ask

logger = logging.getLogger("sudobrain.reports")


def generate_weekly_report() -> dict:
    """Generate a weekly intelligence report covering the last 7 days."""
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    return _generate_report(start_date.isoformat(), end_date.isoformat(), "weekly")


def generate_monthly_report() -> dict:
    """Generate a monthly intelligence report covering the last 30 days."""
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    return _generate_report(start_date.isoformat(), end_date.isoformat(), "monthly")


def _generate_report(start: str, end: str, period: str) -> dict:
    """Gather stats and generate an intelligence report."""
    conn = get_connection()
    try:
        # Meetings count
        meetings = conn.execute(
            "SELECT COUNT(*) as c FROM recordings WHERE created_at >= ? AND created_at <= ? AND status = 'completed'",
            (start, end + "T23:59:59"),
        ).fetchone()["c"]

        # Total recording time
        total_duration = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as d FROM recordings WHERE created_at >= ? AND status = 'completed'",
            (start,),
        ).fetchone()["d"]

        # Decisions made
        decisions = conn.execute(
            "SELECT COUNT(*) as c FROM decisions WHERE created_at >= ?", (start,)
        ).fetchone()["c"]

        decision_list = conn.execute(
            "SELECT text, made_by, project FROM decisions WHERE created_at >= ? ORDER BY created_at DESC LIMIT 10",
            (start,),
        ).fetchall()

        # Tasks created vs completed
        tasks_created = conn.execute(
            "SELECT COUNT(*) as c FROM action_items WHERE created_at >= ?", (start,)
        ).fetchone()["c"]

        tasks_pending = conn.execute(
            "SELECT COUNT(*) as c FROM action_items WHERE status = 'pending'"
        ).fetchone()["c"]

        # Promises
        promises_made = 0
        promises_kept = 0
        promises_broken = 0
        try:
            promises_made = conn.execute(
                "SELECT COUNT(*) as c FROM promises WHERE created_at >= ?", (start,)
            ).fetchone()["c"]
            promises_kept = conn.execute(
                "SELECT COUNT(*) as c FROM promises WHERE status = 'fulfilled' AND created_at >= ?", (start,)
            ).fetchone()["c"]
            promises_broken = conn.execute(
                "SELECT COUNT(*) as c FROM promises WHERE status = 'pending' AND due_date < date('now') AND created_at >= ?",
                (start,),
            ).fetchone()["c"]
        except Exception:
            pass

        # People interacted with
        people_count = 0
        top_people = []
        try:
            from backend.people.graph import init_people_tables
            init_people_tables()
            people_count = conn.execute(
                "SELECT COUNT(DISTINCT person_id) as c FROM person_interactions WHERE interaction_date >= ?",
                (start,),
            ).fetchone()["c"]

            top_people = conn.execute(
                """SELECT p.name, COUNT(pi.id) as interactions
                FROM person_interactions pi JOIN people p ON p.id = pi.person_id
                WHERE pi.interaction_date >= ?
                GROUP BY p.id ORDER BY interactions DESC LIMIT 5""",
                (start,),
            ).fetchall()
        except Exception:
            pass

        # Projects active
        projects = conn.execute(
            "SELECT DISTINCT project FROM action_items WHERE project IS NOT NULL AND created_at >= ?",
            (start,),
        ).fetchall()

        # Sentiment data
        sentiment_data = []
        try:
            rows = conn.execute(
                "SELECT sentiment_score, created_at FROM meeting_sentiment WHERE created_at >= ? ORDER BY created_at",
                (start,),
            ).fetchall()
            sentiment_data = [{"score": r["sentiment_score"], "date": r["created_at"]} for r in rows]
        except Exception:
            pass

    finally:
        conn.close()

    stats = {
        "period": period,
        "start_date": start,
        "end_date": end,
        "meetings": meetings,
        "total_recording_hours": round(total_duration / 3600, 1),
        "decisions_made": decisions,
        "tasks_created": tasks_created,
        "tasks_pending": tasks_pending,
        "promises_made": promises_made,
        "promises_kept": promises_kept,
        "promises_broken": promises_broken,
        "promise_rate": round(promises_kept / max(promises_made, 1) * 100) if promises_made else 0,
        "people_interacted": people_count,
        "top_contacts": [{"name": p["name"], "interactions": p["interactions"]} for p in top_people],
        "active_projects": [p["project"] for p in projects],
        "recent_decisions": [dict(d) for d in decision_list],
        "sentiment_trend": sentiment_data,
    }

    # Generate narrative summary using local reasoning engine
    context = f"""Period: {period} ({start} to {end})

Stats:
- {meetings} meetings ({round(total_duration/3600, 1)} hours of recordings)
- {decisions} decisions made
- {tasks_created} tasks created, {tasks_pending} still pending
- {promises_made} promises made, {promises_kept} kept, {promises_broken} broken/overdue
- Interacted with {people_count} people
- Active projects: {', '.join(p['project'] for p in projects) or 'none tracked'}
- Top contacts: {', '.join(f"{p['name']} ({p['interactions']} interactions)" for p in top_people) or 'none'}"""

    prompt = f"""Generate a concise {period} intelligence report for a personal productivity system.

{context}

Format:
## Highlights
(2-3 key observations)

## Concerns
(anything worrying — overdue items, declining metrics, overcommitment)

## Recommendations
(2-3 actionable suggestions)

Keep it under 200 words. Be direct and specific."""

    try:
        narrative = ask(prompt, max_wait=60)
    except Exception:
        narrative = "Report narrative unavailable because the local reasoning engine is not configured."

    stats["narrative"] = narrative
    stats["generated_at"] = datetime.now().isoformat()

    return stats
