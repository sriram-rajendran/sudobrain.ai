"""Heartbeat engine — periodic DB checks + local reasoning engine analysis when needed.

DB-first: most heartbeats skip LLM work.
Only invokes local reasoning engine when something needs attention.
Notifications are persisted to the database to survive restarts.
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.heartbeat")

_scheduler = None


def _init_notifications_table():
    """Create notifications table if it doesn't exist."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT,
                priority TEXT DEFAULT 'normal',
                read BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read)")
        conn.commit()
    finally:
        conn.close()


def get_notifications() -> list:
    """Get and mark unread notifications as read."""
    _init_notifications_table()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, body, priority, created_at as timestamp FROM notifications WHERE read = FALSE ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        notifs = [dict(r) for r in rows]

        if notifs:
            ids = [n["id"] for n in notifs]
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"UPDATE notifications SET read = TRUE WHERE id IN ({placeholders})", ids)
            conn.commit()

        return notifs
    finally:
        conn.close()


def _push_notification(title: str, body: str, priority: str = "normal"):
    """Persist a notification to the database."""
    _init_notifications_table()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO notifications (title, body, priority) VALUES (?, ?, ?)",
            (title, body, priority),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Notification: %s", title)


def check_overdue_tasks() -> list:
    """Check for overdue action items."""
    conn = get_connection()
    try:
        today = date.today().isoformat()
        rows = conn.execute(
            """SELECT text, assignee, due_date FROM action_items
            WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < ?
            ORDER BY due_date ASC""",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_overdue_promises() -> list:
    """Check for promises overdue by 3+ days."""
    conn = get_connection()
    try:
        threshold = (date.today() - timedelta(days=3)).isoformat()
        rows = conn.execute(
            """SELECT promised_by_name, promised_to_name, description, due_date FROM promises
            WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < ?""",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_pending_reminders() -> list:
    """Check for reminders due now."""
    conn = get_connection()
    try:
        today = date.today().isoformat()
        rows = conn.execute(
            """SELECT text, urgency FROM reminders
            WHERE status = 'pending' AND due_date IS NOT NULL AND due_date <= ?""",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("Reminders check failed (table may not exist): %s", e)
        return []
    finally:
        conn.close()


def process_offline_queue_once(limit: int = 1, recording_id: str = None) -> dict:
    """Process a small batch of queued recordings if any are retryable."""
    try:
        from backend.ai.guardrails import is_emergency_stop_active
        if is_emergency_stop_active():
            return {"processed": [], "failed": [], "total_processed": 0, "total_failed": 0, "skipped": "emergency_stop"}

        from backend.storage.resilience import get_queued_items
        queued = get_queued_items()
        if recording_id:
            queued = [item for item in queued if item.get("recording_id") == recording_id]
        if not queued:
            return {"processed": [], "failed": [], "total_processed": 0, "total_failed": 0}

        from backend.main import process_queue
        return process_queue(limit=max(1, min(limit, 5)), recording_id=recording_id)
    except Exception as e:
        logger.warning("Offline queue processing skipped: %s", e)
        return {"processed": [], "failed": [{"error": str(e)}], "total_processed": 0, "total_failed": 1}


def run_heartbeat():
    """Main heartbeat check — runs every 15 minutes.

    DB-first: checks SQLite directly (free).
    Only calls local reasoning engine if something needs attention.
    """
    try:
        from backend.ai.guardrails import is_emergency_stop_active
        if is_emergency_stop_active():
            logger.info("Heartbeat skipped because emergency stop is active")
            return

        now = datetime.now()

        # Only run during active hours (8 AM - 10 PM)
        if not (8 <= now.hour < 22):
            return

        queue_result = process_offline_queue_once(limit=1)
        if queue_result.get("total_processed") or queue_result.get("total_failed"):
            _push_notification(
                "Offline queue checked",
                f"Processed {queue_result.get('total_processed', 0)}, failed {queue_result.get('total_failed', 0)} queued recording(s).",
                "important" if queue_result.get("total_failed") else "normal",
            )

        overdue_tasks = check_overdue_tasks()
        overdue_promises = check_overdue_promises()
        reminders = check_pending_reminders()

        # If nothing to report, stay silent (zero cost)
        if not overdue_tasks and not overdue_promises and not reminders:
            return

        # Something found — build notification
        parts = []

        if overdue_tasks:
            task_lines = [f"  - {t['text']} ({t['assignee'] or 'unassigned'}, due {t['due_date']})" for t in overdue_tasks[:5]]
            parts.append(f"Overdue tasks ({len(overdue_tasks)}):\n" + "\n".join(task_lines))

        if overdue_promises:
            prom_lines = [f"  - {p['promised_by_name']} to {p['promised_to_name']}: {p['description']} (due {p['due_date']})" for p in overdue_promises]
            parts.append(f"Overdue promises ({len(overdue_promises)}):\n" + "\n".join(prom_lines))

        if reminders:
            rem_lines = [f"  - {r['text']}" for r in reminders[:5]]
            parts.append(f"Due reminders ({len(reminders)}):\n" + "\n".join(rem_lines))

        body = "\n\n".join(parts)
        priority = "important" if overdue_promises else "normal"

        _push_notification("Items need attention", body, priority)

        # Check for upcoming meetings in 15 min window
        try:
            from backend.calendar.client import get_next_meeting, get_meeting_attendees, is_available as cal_ok
            if cal_ok():
                next_meeting = get_next_meeting()
                if next_meeting:
                    start_str = next_meeting.get("start", "")
                    if "T" in start_str:
                        start_dt = datetime.fromisoformat(start_str.replace("Z", ""))
                        minutes_away = (start_dt - datetime.now()).total_seconds() / 60
                        if 5 <= minutes_away <= 20:
                            attendees = get_meeting_attendees(next_meeting)
                            title = next_meeting.get("title", "Meeting")
                            _push_notification(
                                f"Meeting in {int(minutes_away)}min: {title}",
                                f"Attendees: {', '.join(attendees[:4]) or 'none'}",
                                "important",
                            )
        except Exception as e:
            logger.debug("Calendar meeting alert skipped: %s", e)

        # Evaluate workflow rules
        try:
            from backend.intelligence.workflows import evaluate_rules
            evaluate_rules()
        except Exception as e:
            logger.debug("Workflow evaluation skipped: %s", e)

    except Exception as e:
        logger.error("Heartbeat check failed: %s", e)


def generate_morning_briefing() -> dict:
    """Generate a morning briefing using local reasoning engine."""
    from backend.ai.local_llm_engine import ask
    from backend.ai.guardrails import is_emergency_stop_active

    if is_emergency_stop_active():
        return {
            "date": date.today().isoformat(),
            "content": "Emergency stop is active. Proactive analysis and notifications are paused.",
            "overdue_tasks": 0,
            "pending_promises": 0,
            "total_pending_tasks": 0,
            "generated_at": datetime.now().isoformat(),
        }

    overdue_tasks = check_overdue_tasks()

    conn = get_connection()
    try:
        today = date.today().isoformat()

        today_tasks = conn.execute(
            """SELECT text, assignee, due_date FROM action_items
            WHERE status = 'pending' AND due_date = ?""",
            (today,),
        ).fetchall()

        all_pending = conn.execute(
            """SELECT text, assignee, due_date, project FROM action_items
            WHERE status = 'pending' ORDER BY due_date ASC LIMIT 10"""
        ).fetchall()

        promises = conn.execute(
            "SELECT promised_by_name, promised_to_name, description, due_date FROM promises WHERE status = 'pending'"
        ).fetchall()

        unprocessed = conn.execute(
            "SELECT id, mode, created_at FROM recordings WHERE status != 'completed' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    # Build context for local reasoning engine
    context_parts = []

    if overdue_tasks:
        context_parts.append("OVERDUE TASKS:\n" + "\n".join(
            f"- {t['text']} (assignee: {t['assignee']}, due: {t['due_date']})" for t in overdue_tasks
        ))

    if today_tasks:
        context_parts.append("DUE TODAY:\n" + "\n".join(
            f"- {dict(t)['text']} (assignee: {dict(t)['assignee']})" for t in today_tasks
        ))

    if all_pending:
        context_parts.append("ALL PENDING TASKS (top 10):\n" + "\n".join(
            f"- {dict(t)['text']} (assignee: {dict(t)['assignee']}, due: {dict(t)['due_date']}, project: {dict(t)['project']})" for t in all_pending
        ))

    if promises:
        context_parts.append("PENDING PROMISES:\n" + "\n".join(
            f"- {dict(p)['promised_by_name']} to {dict(p)['promised_to_name']}: {dict(p)['description']} (due: {dict(p)['due_date']})" for p in promises
        ))

    # Add calendar context at the top
    try:
        from backend.calendar.client import get_calendar_briefing_context, is_available as cal_ok
        if cal_ok():
            cal_context = get_calendar_briefing_context()
            if cal_context:
                context_parts.insert(0, cal_context)
    except Exception as e:
        logger.debug("Calendar context skipped: %s", e)

    context = "\n\n".join(context_parts) if context_parts else "No pending items found."

    prompt = f"""Generate a concise morning briefing for today ({date.today().strftime('%A, %B %d, %Y')}).

Data:
{context}

Format the briefing with these sections (skip empty sections):
- Today's meetings schedule
- Top priorities for today (max 3)
- Overdue items needing attention
- Promises to keep
- Key deadlines this week

Keep it under 200 words. Be direct. Use bullet points."""

    briefing_text = ask(prompt, max_wait=60)

    return {
        "date": date.today().isoformat(),
        "content": briefing_text,
        "overdue_tasks": len(overdue_tasks),
        "pending_promises": len(promises) if promises else 0,
        "total_pending_tasks": len(all_pending) if all_pending else 0,
        "generated_at": datetime.now().isoformat(),
    }


def _safe_morning_briefing():
    """Wrapper for morning briefing that catches errors."""
    try:
        briefing = generate_morning_briefing()
        _push_notification("Morning Briefing", briefing.get("content", ""), "normal")
    except Exception as e:
        logger.error("Morning briefing failed: %s", e)


def start_scheduler():
    """Start the heartbeat scheduler."""
    global _scheduler
    if _scheduler is not None:
        return

    _init_notifications_table()
    _scheduler = BackgroundScheduler()

    _scheduler.add_job(run_heartbeat, "interval", minutes=15, id="heartbeat",
                       misfire_grace_time=60)

    _scheduler.add_job(_safe_morning_briefing, "cron", hour=8, minute=0,
                       id="morning_briefing", misfire_grace_time=300)

    # Intelligence jobs (overload, decay, project risk, anomalies, etc.)
    try:
        from backend.intelligence.scheduler import register_jobs
        register_jobs(_scheduler)
    except Exception as e:
        logger.warning("intelligence jobs not registered: %s", e)

    if os.getenv("SUDOBRAIN_AUTO_SOURCE_SYNC", "true").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            from backend.source_sync import init_source_sync_log, run_source_sync_once
            init_source_sync_log()
            minutes = int(os.getenv("SUDOBRAIN_SOURCE_SYNC_INTERVAL_MINUTES", "60"))
            _scheduler.add_job(
                run_source_sync_once,
                "interval",
                minutes=max(15, minutes),
                id="source_sync",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
                next_run_time=datetime.now() + timedelta(minutes=2),
            )
            logger.info("Source sync registered every %d min", max(15, minutes))
        except Exception as e:
            logger.warning("source sync not registered: %s", e)

    _scheduler.start()
    logger.info("Scheduler started — heartbeat every 15 min, briefing at 8 AM, intelligence jobs/source sync registered")


def stop_scheduler():
    """Stop the heartbeat scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        logger.info("Scheduler stopped")


def is_scheduler_running() -> bool:
    """Return whether the APScheduler instance is active."""
    return bool(_scheduler and _scheduler.running)
