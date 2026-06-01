"""Read-only source sync orchestration.

Fetches from external systems with read-only credentials, writes normalized
copies into the local SudoBrain database, and records per-source outcomes.
"""

import logging
import os
import json
from datetime import datetime

from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.source_sync")

_RUNNING = False


def init_source_sync_log():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_sync_log (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMPTZ
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_sync_source ON source_sync_log(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_sync_started ON source_sync_log(started_at)")
        conn.commit()
    finally:
        conn.close()


def _log_source(source: str, status: str, detail: str = ""):
    init_source_sync_log()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO source_sync_log (source, status, detail, completed_at)
            VALUES (?, ?, ?, ?)
            """,
            (source, status, _safe_detail(detail), datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _safe_detail(detail) -> str:
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    return detail[:4000]


def _truthy_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def sync_gmail_once() -> dict:
    from backend.gmail.client import get_smart_emails
    from backend.gmail.ingest import (
        append_attachment_text_to_messages,
        backfill_message_validation,
        extract_from_emails,
        init_gmail_tables,
        store_message,
    )

    init_gmail_tables()
    days = int(os.getenv("SUDOBRAIN_GMAIL_SYNC_DAYS", "14"))
    max_results = int(os.getenv("SUDOBRAIN_GMAIL_SYNC_MAX", "50"))
    emails = get_smart_emails(days=days, max_results=max_results)
    stored = sum(1 for email in emails if store_message(email))
    attachment_text = append_attachment_text_to_messages()
    extracted = extract_from_emails(limit=max(stored, 1))
    validation = backfill_message_validation()
    result = {
        "fetched": len(emails),
        "stored": stored,
        "attachment_text": attachment_text,
        "extracted": extracted,
        "validation": validation,
    }
    _log_source("gmail", "completed", result)
    return result


def sync_slack_once() -> dict:
    from backend.slack.sync import sync_all, sync_channels, sync_users
    from backend.slack.ingest import backfill_message_validation, extract_pending_messages

    sync_users()
    sync_channels()
    days = int(os.getenv("SUDOBRAIN_SLACK_SYNC_DAYS", "7"))
    per_channel = int(os.getenv("SUDOBRAIN_SLACK_MESSAGES_PER_CHANNEL", "50"))
    channel_filter = [
        item.strip()
        for item in os.getenv("SUDOBRAIN_SLACK_CHANNEL_FILTER", "").split(",")
        if item.strip()
    ] or None
    result = sync_all(
        channel_filter=channel_filter,
        messages_per_channel=per_channel,
        days=days,
        extract_knowledge=False,
    )
    result["validation"] = backfill_message_validation()
    if _truthy_env("SUDOBRAIN_SLACK_EXTRACT_KNOWLEDGE", False):
        result["extraction"] = extract_pending_messages(
            channel_limit=int(os.getenv("SUDOBRAIN_SLACK_EXTRACT_CHANNEL_LIMIT", "3")),
            batch_size=int(os.getenv("SUDOBRAIN_SLACK_EXTRACT_BATCH_SIZE", "20")),
            max_messages_per_channel=int(os.getenv("SUDOBRAIN_SLACK_EXTRACT_MESSAGES_PER_CHANNEL", "80")),
            max_batches_per_channel=int(os.getenv("SUDOBRAIN_SLACK_EXTRACT_BATCHES_PER_CHANNEL", "1")),
        )
    _log_source("slack", "completed", result)
    return result


def sync_fathom_once() -> dict:
    from backend.fathom.client import is_configured, list_meetings
    from backend.fathom.pipeline import run_fathom_pipeline

    if not is_configured():
        result = {"skipped": "FATHOM_API_TOKEN not configured"}
        _log_source("fathom", "skipped", result)
        return result

    limit = int(os.getenv("SUDOBRAIN_FATHOM_SYNC_LIMIT", "3"))
    meetings = list_meetings(limit=limit)
    # Fathom can return more than requested; enforce our local processing limit.
    items = meetings.get("items", [])[:limit]

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT transcript_json FROM transcripts WHERE full_text IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    processed = set()
    import json
    for row in rows:
        try:
            payload = json.loads(row["transcript_json"])
            fid = (payload.get("fathom") or {}).get("fathom_recording_id")
            engine = (payload.get("processing") or {}).get("engine")
            source = payload.get("source")
            if fid and (engine == "sarvam" or source == "fathom_meeting"):
                processed.add(str(fid))
        except Exception:
            continue

    completed = []
    skipped = []
    for meeting in items:
        rid = str(meeting.get("recording_id") or "")
        share_url = meeting.get("share_url") or meeting.get("url") or ""
        if not rid or rid in processed:
            skipped.append(rid)
            continue
        if not share_url:
            skipped.append(rid)
            continue
        completed.append(run_fathom_pipeline(rid, share_url))

    result = {"found": len(items), "processed": len(completed), "skipped": len(skipped)}
    _log_source("fathom", "completed", result)
    return result


def sync_project_context_once() -> dict:
    from backend.projects.context import sync_project_context

    result = sync_project_context()
    _log_source("project_context", "completed", {
        "repositories_found": result.get("repositories_found"),
        "projects_synced": result.get("projects_synced"),
    })
    return result


def run_source_sync_once() -> dict:
    """Run all enabled source syncs once, without overlapping itself."""
    global _RUNNING
    if _RUNNING:
        return {"status": "skipped", "reason": "already_running"}

    _RUNNING = True
    results = {}
    try:
        for source, enabled, fn in [
            ("gmail", _truthy_env("SUDOBRAIN_SYNC_GMAIL", False), sync_gmail_once),
            ("slack", _truthy_env("SUDOBRAIN_SYNC_SLACK", False), sync_slack_once),
            ("fathom", _truthy_env("SUDOBRAIN_SYNC_FATHOM", False), sync_fathom_once),
            ("project_context", _truthy_env("SUDOBRAIN_SYNC_PROJECT_CONTEXT", False), sync_project_context_once),
        ]:
            if not enabled:
                results[source] = {"skipped": "disabled"}
                continue
            try:
                results[source] = fn()
            except Exception as e:
                logger.exception("%s sync failed", source)
                _log_source(source, "failed", str(e))
                results[source] = {"error": str(e)}
        try:
            from backend.source_audit import collect_source_audit
            results["audit"] = collect_source_audit()
        except Exception as e:
            logger.warning("source audit after sync failed: %s", e)
        return {"status": "completed", "sources": results}
    finally:
        _RUNNING = False
