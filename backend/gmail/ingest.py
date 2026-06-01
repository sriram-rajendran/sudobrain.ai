"""Gmail ingestion — fetch emails, extract knowledge, store in Postgres."""

import json
import logging
import os
from datetime import datetime
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.gmail.ingest")

PROJECT_KEYWORDS = {
    item.strip().lower()
    for item in os.getenv("SUDOBRAIN_PROJECT_KEYWORDS", "").split(",")
    if item.strip()
}
INTERNAL_EMAIL_DOMAINS = {
    item.strip().lower().lstrip("@")
    for item in os.getenv("SUDOBRAIN_INTERNAL_EMAIL_DOMAINS", "").split(",")
    if item.strip()
}

CALENDAR_SUBJECT_PREFIXES = (
    "invitation:",
    "updated invitation:",
    "canceled event:",
    "cancelled event:",
)


def init_gmail_tables():
    """Create Gmail storage tables."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS gmail_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                subject TEXT,
                from_email TEXT,
                from_name TEXT,
                to_emails TEXT,
                date TIMESTAMPTZ,
                snippet TEXT,
                body TEXT,
                labels TEXT,
                validation_status TEXT DEFAULT 'valid',
                validation_reason TEXT DEFAULT 'human_email_filter_passed',
                extracted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE gmail_messages ADD COLUMN IF NOT EXISTS validation_status TEXT DEFAULT 'valid';
            ALTER TABLE gmail_messages ADD COLUMN IF NOT EXISTS validation_reason TEXT DEFAULT 'human_email_filter_passed';
            ALTER TABLE gmail_messages ALTER COLUMN date TYPE TIMESTAMPTZ USING (date AT TIME ZONE 'UTC');
            ALTER TABLE gmail_messages ALTER COLUMN created_at TYPE TIMESTAMPTZ USING (created_at AT TIME ZONE 'UTC');
            UPDATE gmail_messages
            SET validation_status = COALESCE(validation_status, 'valid'),
                validation_reason = COALESCE(validation_reason, 'human_email_filter_passed')
            WHERE validation_status IS NULL OR validation_reason IS NULL;

            CREATE TABLE IF NOT EXISTS gmail_sync_log (
                id SERIAL PRIMARY KEY,
                query TEXT,
                messages_fetched INTEGER DEFAULT 0,
                knowledge_extracted INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_gmail_thread ON gmail_messages(thread_id);
            CREATE INDEX IF NOT EXISTS idx_gmail_date ON gmail_messages(date);
            CREATE INDEX IF NOT EXISTS idx_gmail_extracted ON gmail_messages(extracted);
            CREATE INDEX IF NOT EXISTS idx_gmail_from ON gmail_messages(from_email);
        """)
        conn.commit()
    finally:
        conn.close()


def store_message(msg: dict) -> str:
    """Store a Gmail message. Returns message id."""
    validation_status, validation_reason = validate_message(msg)
    if validation_status != "valid":
        logger.debug(
            "Skipping Gmail message %s: %s",
            validation_reason,
            msg.get("subject", ""),
        )
        return ""

    init_gmail_tables()
    conn = get_connection()
    try:
        msg_id = msg.get("id")
        if not msg_id:
            return ""

        from_field = msg.get("from", "")
        from_name, from_email = _parse_email_field(from_field)
        to_emails = json.dumps(msg.get("to", []))
        labels = json.dumps(msg.get("labels", []))

        # Include attachment info in body for extraction context
        body = msg.get("body", "") or ""
        attachments = msg.get("attachments", [])
        if attachments:
            attach_info = "\n\n[Attachments: " + ", ".join(
                f"{a.get('name', '?')} ({a.get('type', '?')}, {a.get('size_kb', '?')}KB)"
                for a in attachments
            ) + "]"
            body = body + attach_info

        conn.execute("""
            INSERT INTO gmail_messages
            (id, thread_id, subject, from_email, from_name, to_emails, date, snippet, body, labels,
             validation_status, validation_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                validation_status = EXCLUDED.validation_status,
                validation_reason = EXCLUDED.validation_reason,
                body = EXCLUDED.body,
                labels = EXCLUDED.labels
        """, (
            msg_id, msg.get("thread_id"), msg.get("subject"),
            from_email, from_name, to_emails,
            msg.get("date"), msg.get("snippet"), body,
            labels,
            validation_status,
            validation_reason,
        ))
        conn.commit()
        return msg_id
    finally:
        conn.close()


def extract_from_emails(limit: int = 50) -> int:
    """Run knowledge extraction on unextracted emails."""
    from backend.ai.local_llm_engine import extract_knowledge
    from backend.graph.neo4j_client import ingest_knowledge
    from backend.storage import database as db

    init_gmail_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, subject, from_name, from_email, body, date
            FROM gmail_messages
            WHERE extracted = FALSE AND body IS NOT NULL AND LENGTH(body) > 50
            ORDER BY date DESC LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    logger.info("Extracting knowledge from %d emails", len(rows))
    processed = 0

    for r in rows:
        msg = dict(r._row) if hasattr(r, '_row') else dict(r)
        body = msg.get("body", "")
        subject = msg.get("subject", "")
        body_for_extraction = _trim_for_extraction(body)

        # Format as conversation for local reasoning engine
        email_text = f"[Email from {msg.get('from_name') or msg.get('from_email', 'Unknown')}]\nSubject: {subject}\n\n{body_for_extraction}"
        extraction_ok = False

        try:
            knowledge = extract_knowledge(email_text)
            if knowledge:
                synthetic_tid = f"email_{msg['id']}"
                rec_id = f"gmail_{msg['id']}"
                db.save_recording(rec_id, "email", f"gmail://{msg['id']}", 0)

                transcript_stub = {
                    "id": synthetic_tid,
                    "recording_id": rec_id,
                    "source": "email",
                    "created_at": datetime.now().isoformat(),
                    "duration_seconds": 0,
                    "language": {"primary": "en", "detected": ["en"], "is_code_mixed": False},
                    "participants": [],
                    "segments": [{"speaker_id": msg.get("from_email", "email"),
                                  "start_seconds": 0, "end_seconds": 0,
                                  "text": body_for_extraction[:2000], "language": "en"}],
                    "full_transcript": email_text,
                    "processing": {"engine": "email", "model": "n/a",
                                   "processed_at": datetime.now().isoformat(),
                                   "audio_preprocessing": []},
                }
                db.save_transcript(transcript_stub)

                for item in knowledge.get("action_items", []):
                    db.save_action_item(
                        transcript_id=synthetic_tid,
                        text=item.get("text", ""),
                        assignee=item.get("assignee"),
                        project=knowledge.get("project"),
                        due_date=item.get("due_date"),
                    )
                for item in knowledge.get("decisions", []):
                    db.save_decision(
                        transcript_id=synthetic_tid,
                        text=item.get("text", ""),
                        made_by=item.get("made_by") or msg.get("from_name"),
                        context=item.get("context"),
                        project=knowledge.get("project"),
                    )

                try:
                    ingest_knowledge(knowledge, synthetic_tid,
                                     meeting_date=msg.get("date"),
                                     participants=[msg.get("from_name") or msg.get("from_email", "")])
                except Exception as e:
                    logger.debug("Graph ingestion skipped for email: %s", e)

                processed += 1
            extraction_ok = True
        except Exception as e:
            logger.warning("Email extraction failed for %s: %s", msg["id"], e)

        # Mark as extracted
        if not extraction_ok:
            continue
        conn = get_connection()
        try:
            conn.execute("UPDATE gmail_messages SET extracted = TRUE WHERE id = ?", (msg["id"],))
            conn.commit()
        finally:
            conn.close()

    return processed


def get_email_stats() -> dict:
    """Get Gmail sync statistics."""
    init_gmail_tables()
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM gmail_messages").fetchone()["c"]
        extracted = conn.execute("SELECT COUNT(*) as c FROM gmail_messages WHERE extracted = TRUE").fetchone()["c"]
        unread_count = conn.execute("SELECT COUNT(*) as c FROM gmail_messages WHERE labels LIKE '%UNREAD%'").fetchone()["c"]
        last = conn.execute("SELECT MAX(completed_at) as d FROM gmail_sync_log WHERE status='completed'").fetchone()
        return {
            "total_emails": total,
            "extracted": extracted,
            "unread": unread_count,
            "last_sync": last["d"] if last else None,
        }
    finally:
        conn.close()


def validate_message(msg: dict) -> tuple[str, str]:
    """Classify whether a Gmail message should enter the knowledge base."""
    from backend.gmail.client import is_dump_email

    if not msg.get("id"):
        return "ignored", "missing_message_id"
    if is_dump_email(msg):
        return "ignored", "automated_or_promotional_filter"

    subject = (msg.get("subject") or "").strip()
    body = (msg.get("body") or "").strip()
    attachments = msg.get("attachments") or []
    from_field = (msg.get("from") or "").lower()
    haystack = f"{subject}\n{body}".lower()

    if not subject and not body and not attachments:
        return "ignored", "empty_message"

    useful_attachments = [
        a for a in attachments
        if (a.get("type") or "").lower().lstrip(".") in {
            "pdf", "doc", "docx", "txt", "md", "csv", "xlsx",
            "png", "jpg", "jpeg", "gif", "webp", "svg",
        }
    ]
    if useful_attachments and any(k in haystack for k in PROJECT_KEYWORDS):
        return "valid", "project_attachment"
    if any(k in haystack for k in PROJECT_KEYWORDS):
        return "valid", "project_context"
    if subject.lower().startswith(CALENDAR_SUBJECT_PREFIXES):
        if _is_internal_sender(from_field) or any(k in haystack for k in PROJECT_KEYWORDS):
            return "valid", "calendar_work_context"
        return "ignored", "calendar_without_project_context"
    if _is_internal_sender(from_field):
        return "valid", "internal_work_context"
    if body or useful_attachments:
        return "valid", "human_email_filter_passed"
    return "ignored", "insufficient_content"


def _is_internal_sender(from_field: str) -> bool:
    return any(f"@{domain}" in from_field for domain in INTERNAL_EMAIL_DOMAINS)


def backfill_message_validation() -> dict:
    """Reclassify already stored Gmail rows using the current rules."""
    init_gmail_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, subject, from_email, from_name, body, labels
            FROM gmail_messages
        """).fetchall()
        updated = 0
        ignored = 0
        valid = 0
        for row in rows:
            msg = {
                "id": row["id"],
                "subject": row["subject"],
                "from": f"{row['from_name'] or ''} <{row['from_email'] or ''}>",
                "body": row["body"],
                "labels": json.loads(row["labels"] or "[]"),
            }
            status, reason = validate_message(msg)
            if status == "valid":
                valid += 1
            else:
                ignored += 1
            conn.execute(
                """
                UPDATE gmail_messages
                SET validation_status = ?, validation_reason = ?
                WHERE id = ?
                """,
                (status, reason, row["id"]),
            )
            updated += 1
        conn.commit()
        return {"updated": updated, "valid": valid, "ignored": ignored}
    finally:
        conn.close()


def append_attachment_text_to_messages(max_chars_per_attachment: int = 8000) -> dict:
    """Append locally extracted attachment text into Gmail message bodies."""
    init_gmail_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT message_id, filename, file_type, extracted_text
            FROM gmail_attachments
            WHERE char_count > 0
            ORDER BY message_id, filename
        """).fetchall()
        by_message: dict[str, list[dict]] = {}
        for row in rows:
            by_message.setdefault(row["message_id"], []).append(dict(row))

        updated = 0
        for message_id, attachments in by_message.items():
            msg = conn.execute(
                "SELECT body FROM gmail_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if not msg:
                continue
            body = msg["body"] or ""
            parts = []
            for attachment in attachments:
                marker = f"--- Attachment: {attachment['filename']} ({attachment['file_type']}) ---"
                if marker in body:
                    continue
                text = (attachment["extracted_text"] or "").strip()
                if not text:
                    continue
                parts.append(f"\n\n{marker}\n{text[:max_chars_per_attachment]}")
            if not parts:
                continue
            conn.execute(
                """
                UPDATE gmail_messages
                SET body = ?, extracted = FALSE
                WHERE id = ?
                """,
                (body + "".join(parts), message_id),
            )
            updated += 1
        conn.commit()
        return {"messages_updated": updated, "messages_with_attachment_text": len(by_message)}
    finally:
        conn.close()


def _trim_for_extraction(body: str, max_chars: int = 12000) -> str:
    body = body or ""
    marker = "--- Attachment:"
    if len(body) <= max_chars:
        return body
    if marker not in body:
        return body[:max_chars]
    head = body[:3000]
    attachment_start = body.find(marker)
    attachment_text = body[attachment_start:]
    remaining = max(max_chars - len(head) - 20, 0)
    return f"{head}\n\n[...]\n\n{attachment_text[:remaining]}"


def _parse_email_field(field: str) -> tuple[str, str]:
    """Parse 'Name <email@example.com>' into (name, email)."""
    if not field:
        return "", ""
    if "<" in field and ">" in field:
        name = field.split("<")[0].strip().strip('"')
        email = field.split("<")[1].split(">")[0].strip()
        return name, email
    return "", field.strip()
