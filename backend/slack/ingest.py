"""Slack message ingestion — stores messages and runs knowledge extraction on high-signal content."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from backend.storage.database import get_connection
from backend.slack.schema import init_slack_tables

logger = logging.getLogger("sudobrain.slack.ingest")


DM_ACTION_PATTERNS = [
    r"\b(action|todo|task|follow[- ]?up|owner|assign|deadline|due|blocked|blocker)\b",
    r"\b(can you|could you|please|need to|needs to|we need|i need|let'?s|should)\b",
    r"\b(fix|build|implement|update|review|check|verify|test|deploy|ship|send|share|schedule|call)\b",
    r"\b(decision|decided|approved|approve|go with|choose|finalize|confirmed)\b",
    r"\b(i'?ll|i will|we will|will do|promise|committed|commit to)\b",
]

DM_PROJECT_PATTERNS = [
    rf"\b{re.escape(item.strip().lower())}\b"
    for item in os.getenv("SUDOBRAIN_PROJECT_KEYWORDS", "").split(",")
    if item.strip()
]


def store_user(user: dict) -> str:
    """Store a Slack user, link to people graph if email matches."""
    init_slack_tables()
    conn = get_connection()
    try:
        uid = user.get("id")
        if not uid:
            return ""

        # Try to link to existing person by email
        person_id = None
        email = user.get("email", "").strip().lower()
        if email:
            row = conn.execute(
                "SELECT id FROM people WHERE LOWER(email) = ?", (email,)
            ).fetchone()
            if row:
                person_id = row["id"]
            else:
                # Create person
                from backend.people.graph import get_or_create_person
                person_id = get_or_create_person(
                    user.get("real_name") or user.get("name") or email,
                    email=email,
                )

        conn.execute("""
            INSERT INTO slack_users
            (id, name, real_name, email, title, timezone, is_bot, deleted, person_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                real_name = EXCLUDED.real_name,
                email = COALESCE(EXCLUDED.email, slack_users.email),
                title = EXCLUDED.title,
                person_id = COALESCE(EXCLUDED.person_id, slack_users.person_id),
                updated_at = EXCLUDED.updated_at
        """, (
            uid, user.get("name"), user.get("real_name"),
            email or None, user.get("title"), user.get("timezone"),
            user.get("is_bot", False), user.get("deleted", False),
            person_id, datetime.now().isoformat(),
        ))
        conn.commit()
        return uid
    finally:
        conn.close()


def store_channel(channel: dict) -> str:
    """Store a Slack channel."""
    init_slack_tables()
    conn = get_connection()
    try:
        cid = channel.get("id")
        if not cid:
            return ""
        name = channel.get("name") or ""
        is_dm = bool(channel.get("is_dm")) or name.startswith("dm:") or name.startswith("mpdm-")

        conn.execute("""
            INSERT INTO slack_channels
            (id, name, topic, purpose, is_private, is_dm, is_archived, member_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                topic = EXCLUDED.topic,
                purpose = EXCLUDED.purpose,
                is_private = EXCLUDED.is_private,
                is_dm = EXCLUDED.is_dm,
                is_archived = EXCLUDED.is_archived,
                member_count = EXCLUDED.member_count
        """, (
            cid, name, channel.get("topic", ""),
            channel.get("purpose", ""), channel.get("is_private", False),
            is_dm, channel.get("is_archived", False), channel.get("member_count", 0),
            datetime.now().isoformat(),
        ))
        conn.commit()
        return cid
    finally:
        conn.close()


def store_message(channel_id: str, msg: dict) -> int:
    """Store a Slack message. Returns row id or 0."""
    init_slack_tables()
    conn = get_connection()
    try:
        ts = msg.get("ts")
        if not ts:
            return 0

        try:
            message_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError):
            message_at = None

        mentions = msg.get("mentions", [])
        reactions = msg.get("reactions", [])
        reaction_count = sum(len(r.get("users", [])) for r in reactions)

        validation = validate_message({
            "text": msg.get("text", ""),
            "is_bot_message": msg.get("is_bot", False),
            "is_dm": _is_dm_channel(conn, channel_id),
            "has_files": bool(msg.get("files")),
        })

        cursor = conn.execute("""
            INSERT INTO slack_messages
            (ts, message_at, channel_id, user_id, user_name, text, thread_ts,
             is_thread_parent, reply_count, reaction_count, mention_users,
             is_bot_message, validation_status, validation_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (channel_id, ts) DO UPDATE SET
                message_at = EXCLUDED.message_at,
                text = EXCLUDED.text,
                user_name = EXCLUDED.user_name,
                reply_count = EXCLUDED.reply_count,
                reaction_count = EXCLUDED.reaction_count,
                is_bot_message = EXCLUDED.is_bot_message,
                validation_status = EXCLUDED.validation_status,
                validation_reason = EXCLUDED.validation_reason
        """, (
            ts, message_at, channel_id,
            msg.get("user_id"), msg.get("user_name"),
            msg.get("text", ""),
            msg.get("thread_ts"),
            bool(msg.get("reply_count", 0) > 0),
            msg.get("reply_count", 0),
            reaction_count,
            json.dumps(mentions) if mentions else None,
            msg.get("is_bot", False),
            validation["status"],
            validation["reason"],
        ))
        msg_id = cursor.lastrowid

        # Store reactions
        if reactions and msg_id:
            for r in reactions:
                emoji = r.get("emoji", "")
                for uid in r.get("users", []):
                    conn.execute(
                        "INSERT INTO slack_reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
                        (msg_id, uid, emoji),
                    )

        # Store file metadata + extract text from small PDFs/docs
        files = msg.get("files") or []
        if files:
            _store_message_files(conn, channel_id, ts, files)

        conn.commit()
        return msg_id
    finally:
        conn.close()


def _is_dm_channel(conn, channel_id: str) -> bool:
    row = conn.execute(
        "SELECT is_dm, name FROM slack_channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    if not row:
        return False
    name = row["name"] or ""
    return bool(row["is_dm"]) or name.startswith("dm:") or name.startswith("mpdm-")


def _store_message_files(conn, channel_id: str, message_ts: str, files: list):
    """Store Slack file metadata + extract text from supported types."""
    from backend.slack.client import download_slack_file
    from backend.gmail.attachments import extract_text, TEXT_EXTRACTABLE

    for f in files:
        fid = f.get("id")
        if not fid:
            continue
        filetype = (f.get("filetype") or "").lower()
        extracted = ""
        # Only download small (< 5 MB) text-extractable files
        if filetype in TEXT_EXTRACTABLE and f.get("size", 0) < 5 * 1024 * 1024:
            try:
                raw = download_slack_file(f.get("url_private_download") or f.get("url_private", ""))
                extracted = extract_text(f.get("name", ""), filetype, raw)
            except Exception as e:
                logger.debug("slack file extract failed %s: %s", fid, e)
        conn.execute("""
            INSERT INTO slack_files
            (id, channel_id, message_ts, filename, filetype, mimetype, size,
             url_private, extracted_text, char_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                extracted_text = EXCLUDED.extracted_text,
                char_count = EXCLUDED.char_count
        """, (
            fid, channel_id, message_ts,
            f.get("name", ""), filetype, f.get("mimetype", ""),
            f.get("size", 0), f.get("url_private"),
            extracted, len(extracted),
        ))


def validate_message(msg: dict) -> dict:
    """Classify whether a Slack message should feed knowledge extraction.

    Filters out only pure noise:
    - Empty text
    - System messages (joins, leaves, channel renames)
    - Very short reactions/acknowledgments (<5 chars like 'ok', '+1')

    Channel messages are allowed when their channel is enabled. Direct messages
    are intentionally stricter: they must contain task, decision, promise,
    project, or file/context signals before they feed knowledge extraction.
    """
    text = (msg.get("text") or "").strip()
    if not text:
        return {"valid": False, "status": "ignored", "reason": "empty_text"}

    # System messages
    system_patterns = [
        "has joined the channel",
        "has left the channel",
        "set the channel",
        "renamed the channel",
        "pinned a message",
        "unpinned a message",
        "added an integration",
    ]
    lower = text.lower()
    for p in system_patterns:
        if p in lower:
            return {"valid": False, "status": "ignored", "reason": "system_message"}

    # Minimum meaningful length (skip 'ok', 'lol', emoji-only)
    if len(text) < 5:
        return {"valid": False, "status": "ignored", "reason": "too_short"}

    if re.fullmatch(r"[:+\\-\\s\\w]+", text) and len(text.split()) <= 2:
        emojiish = text.strip(": +-\t\n").lower()
        if emojiish in {"ok", "okay", "yes", "no", "done", "lol", "thanks", "thankyou"}:
            return {"valid": False, "status": "ignored", "reason": "acknowledgement"}

    if msg.get("is_dm"):
        dm_signal = _dm_knowledge_signal(text, bool(msg.get("has_files")))
        if not dm_signal:
            return {"valid": False, "status": "ignored", "reason": "dm_low_signal"}
        return {"valid": True, "status": "valid", "reason": f"dm_{dm_signal}"}

    reason = "bot_context" if msg.get("is_bot_message") else "human_context"
    return {"valid": True, "status": "valid", "reason": reason}


def _dm_knowledge_signal(text: str, has_files: bool = False) -> str | None:
    """Return why a DM is worth extraction, or None for casual chat."""
    lower = (text or "").lower()
    has_action = any(re.search(pattern, lower) for pattern in DM_ACTION_PATTERNS)
    has_project = any(re.search(pattern, lower) for pattern in DM_PROJECT_PATTERNS)

    if has_action and has_project:
        return "work_context"
    if has_action and len(lower.split()) >= 8:
        return "action_context"
    if has_project and len(lower.split()) >= 12:
        return "project_context"
    if has_files and (has_action or has_project or len(lower.split()) >= 8):
        return "file_context"
    return None


def is_extractable(msg: dict) -> bool:
    """Check if a message is worth including in extraction."""
    return validate_message(msg)["valid"]


def backfill_message_validation(limit: int = 5000) -> dict:
    """Validate stored Slack rows that predate validation or are out of scope."""
    init_slack_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT m.id, m.text, m.is_bot_message,
                   c.sync_enabled, c.is_archived, c.name as channel_name, c.is_dm,
                   EXISTS (
                       SELECT 1 FROM slack_files f
                       WHERE f.channel_id = m.channel_id AND f.message_ts = m.ts
                   ) AS has_files
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.validation_status IS NULL
               OR m.validation_status = 'unvalidated'
               OR m.validation_reason IS NULL
               OR m.validation_reason = 'previously_extracted'
               OR c.sync_enabled = FALSE
               OR c.is_archived = TRUE
               OR c.is_dm = TRUE
               OR LEFT(c.name, 3) = 'dm:'
               OR LEFT(c.name, 5) = 'mpdm-'
            ORDER BY m.id ASC
            LIMIT ?
        """, (limit,)).fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            msg = dict(row._row) if hasattr(row, "_row") else dict(row)
            channel_name = msg.get("channel_name") or ""
            is_dm = bool(msg.get("is_dm")) or channel_name.startswith("dm:") or channel_name.startswith("mpdm-")
            if is_dm and (msg.get("is_archived") or not msg.get("sync_enabled")):
                validation = {"status": "ignored", "reason": "dm_not_enabled"}
                extracted = True
            elif msg.get("is_archived") or not msg.get("sync_enabled"):
                validation = {"status": "ignored", "reason": "disabled_channel"}
                extracted = True
            else:
                validation = validate_message(msg)
                extracted = validation["status"] == "ignored"

            counts[validation["reason"]] = counts.get(validation["reason"], 0) + 1
            conn.execute(
                """
                UPDATE slack_messages
                SET validation_status = ?,
                    validation_reason = ?,
                    extracted = CASE WHEN ? THEN TRUE ELSE extracted END
                WHERE id = ?
                """,
                (
                    validation["status"],
                    validation["reason"],
                    extracted,
                    msg["id"],
                ),
            )
        conn.commit()
        return {"validated": len(rows), "reasons": counts}
    finally:
        conn.close()


def extract_from_messages(
    channel_id: str,
    batch_size: int = 30,
    max_messages: int = 1000,
    max_batches: int | None = None,
) -> int:
    """Run knowledge extraction on ALL unextracted messages in a channel.

    Groups messages into conversational batches (by time proximity + threads)
    and runs extraction on each batch. One local reasoning engine call per batch for efficiency.

    Returns count of messages processed.
    """
    from backend.ai.local_llm_engine import extract_knowledge
    from backend.graph.neo4j_client import ingest_knowledge
    from backend.storage import database as db

    init_slack_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT m.id, m.ts, m.channel_id, m.user_id, m.user_name, m.text,
                   m.thread_ts, m.reply_count, m.mention_users, m.reaction_count,
                   c.name as channel_name, c.is_dm,
                   EXISTS (
                       SELECT 1 FROM slack_files f
                       WHERE f.channel_id = m.channel_id AND f.message_ts = m.ts
                   ) AS has_files
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.channel_id = ?
              AND m.extracted = FALSE
            ORDER BY m.ts ASC
            LIMIT ?
        """, (channel_id, max_messages)).fetchall()
    finally:
        conn.close()

    # Filter out pure noise (bots, system messages, one-word reactions)
    extractable = []
    ignored_ids = []
    for r in rows:
        msg = dict(r._row) if hasattr(r, '_row') else dict(r)
        validation = validate_message(msg)
        msg["validation_status"] = validation["status"]
        msg["validation_reason"] = validation["reason"]
        if validation["valid"]:
            extractable.append(msg)
        else:
            ignored_ids.append((msg["id"], validation["reason"]))

    if ignored_ids:
        conn = get_connection()
        try:
            for mid, reason in ignored_ids:
                conn.execute(
                    """
                    UPDATE slack_messages
                    SET validation_status = 'ignored',
                        validation_reason = ?,
                        extracted = TRUE
                    WHERE id = ?
                    """,
                    (reason, mid),
                )
            conn.commit()
        finally:
            conn.close()

    if not extractable:
        logger.info("No extractable messages in channel %s", channel_id)
        return 0

    logger.info("Extracting from %d/%d messages in channel %s",
                len(extractable), len(rows), channel_id)

    # Batch process
    processed = 0
    for batch_index, i in enumerate(range(0, len(extractable), batch_size)):
        if max_batches is not None and batch_index >= max_batches:
            break
        batch = extractable[i:i + batch_size]
        batch_text = _format_batch_for_extraction(batch)
        extraction_ok = False

        try:
            knowledge = extract_knowledge(batch_text)
            if knowledge:
                # Create a synthetic transcript_id for this batch
                from datetime import datetime
                first_ts = str(batch[0].get("ts", "")).replace(".", "")
                last_ts = str(batch[-1].get("ts", "")).replace(".", "")
                synthetic_tid = f"slack_{channel_id}_{first_ts}_{last_ts}"

                # Save a stable recording/transcript stub so repeated extraction is idempotent.
                rec_id = f"rec_{synthetic_tid}"
                db.save_recording(
                    rec_id,
                    "slack_batch",
                    f"slack://{batch[0]['channel_name']}/{synthetic_tid}",
                    0,
                )

                transcript_stub = {
                    "id": synthetic_tid,
                    "recording_id": rec_id,
                    "source": "slack",
                    "created_at": datetime.now().isoformat(),
                    "duration_seconds": 0,
                    "language": {"primary": "en", "detected": ["en"], "is_code_mixed": False},
                    "participants": [],
                    "segments": [{"speaker_id": m.get("user_id", "unknown"),
                                  "start_seconds": 0, "end_seconds": 0,
                                  "text": m.get("text", ""), "language": "en"} for m in batch],
                    "full_transcript": batch_text,
                    "processing": {"engine": "slack", "model": "n/a",
                                   "processed_at": datetime.now().isoformat(),
                                   "audio_preprocessing": []},
                }
                db.save_transcript(transcript_stub)

                # Save extracted knowledge
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
                        made_by=item.get("made_by"),
                        context=item.get("context"),
                        project=knowledge.get("project"),
                    )
                for item in knowledge.get("promises", []):
                    _save_promise(synthetic_tid, item)

                # Ingest into Neo4j graph
                try:
                    ingest_knowledge(knowledge, synthetic_tid,
                                     meeting_date=datetime.now().isoformat(),
                                     participants=[m.get("user_name", "") for m in batch if m.get("user_name")])
                except Exception as e:
                    logger.warning("Graph ingestion failed for slack batch: %s", e)

                logger.info("Extracted from batch: %d actions, %d decisions, %d promises",
                            len(knowledge.get("action_items", [])),
                            len(knowledge.get("decisions", [])),
                            len(knowledge.get("promises", [])))
            extraction_ok = True
        except Exception as e:
            logger.warning("Knowledge extraction failed for batch: %s", e)

        # Mark as extracted
        if not extraction_ok:
            continue
        msg_ids = [m["id"] for m in batch]
        conn = get_connection()
        try:
            placeholders = ",".join("?" * len(msg_ids))
            conn.execute(
                f"UPDATE slack_messages SET extracted = TRUE WHERE id IN ({placeholders})",
                msg_ids,
            )
            conn.commit()
        finally:
            conn.close()

        processed += len(batch)

    return processed


def extract_pending_messages(
    channel_limit: int = 5,
    batch_size: int = 20,
    max_messages_per_channel: int = 100,
    max_batches_per_channel: int = 1,
) -> dict:
    """Run bounded Slack knowledge extraction across enabled channels."""
    backfill = backfill_message_validation()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT c.id, c.name, COUNT(m.id) as pending
            FROM slack_channels c
            JOIN slack_messages m ON m.channel_id = c.id
            WHERE c.sync_enabled = TRUE
              AND c.is_archived = FALSE
              AND m.extracted = FALSE
              AND m.validation_status = 'valid'
            GROUP BY c.id, c.name
            ORDER BY pending DESC, c.name
            LIMIT ?
        """, (channel_limit,)).fetchall()
    finally:
        conn.close()

    results = []
    total = 0
    for row in rows:
        r = dict(row._row) if hasattr(row, "_row") else dict(row)
        try:
            processed = extract_from_messages(
                r["id"],
                batch_size=batch_size,
                max_messages=max_messages_per_channel,
                max_batches=max_batches_per_channel,
            )
            total += processed
            results.append({"channel": r["name"], "pending": r["pending"], "processed": processed})
        except Exception as e:
            logger.warning("Slack extraction failed for %s: %s", r["name"], e)
            results.append({"channel": r["name"], "pending": r["pending"], "error": str(e)})

    return {"validated": backfill, "total_processed": total, "channels": results}


def _format_batch_for_extraction(messages: list[dict]) -> str:
    """Format a batch of Slack messages as a conversation for local reasoning engine.

    Preserves channel context, timestamps, thread structure.
    """
    from datetime import datetime

    lines = []
    if messages:
        channel = messages[0].get("channel_name", "unknown")
        if messages[0].get("is_dm") or str(channel).startswith(("dm:", "mpdm-")):
            lines.append(f"[Slack direct-message conversation from {channel}]")
            lines.append("Only extract explicit work actions, decisions, promises, or project facts. Ignore casual chat.")
        else:
            lines.append(f"[Slack conversation from #{channel}]")
        lines.append("")

    # Group by thread for better context
    thread_groups = {}
    main_msgs = []
    for m in messages:
        tts = m.get("thread_ts")
        if tts and tts != m.get("ts"):
            if tts not in thread_groups:
                thread_groups[tts] = []
            thread_groups[tts].append(m)
        else:
            main_msgs.append(m)

    for m in main_msgs:
        ts_str = ""
        try:
            ts_float = float(m.get("ts", 0))
            ts_str = datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass

        who = m.get("user_name") or m.get("user_id", "Unknown")
        text = (m.get("text") or "").strip()
        if text:
            lines.append(f"[{ts_str}] {who}: {text}")

            # Add thread replies if any
            msg_ts = m.get("ts")
            if msg_ts in thread_groups:
                for reply in thread_groups[msg_ts]:
                    r_who = reply.get("user_name") or reply.get("user_id", "Unknown")
                    r_text = (reply.get("text") or "").strip()
                    if r_text:
                        lines.append(f"    └─ {r_who}: {r_text}")

    return "\n".join(lines)


def _save_promise(transcript_id: str, item: dict):
    """Save a promise (reuses main.py logic)."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id TEXT,
                promised_by_name TEXT,
                promised_to_name TEXT,
                description TEXT NOT NULL,
                detected_text TEXT,
                due_date DATE,
                status TEXT DEFAULT 'pending',
                reminder_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing = conn.execute(
            """
            SELECT id FROM promises
            WHERE transcript_id = ?
              AND LOWER(REGEXP_REPLACE(COALESCE(description, ''), '\\s+', ' ', 'g')) =
                  LOWER(REGEXP_REPLACE(COALESCE(?, ''), '\\s+', ' ', 'g'))
              AND COALESCE(LOWER(promised_by_name), '') = COALESCE(LOWER(?), '')
              AND COALESCE(LOWER(promised_to_name), '') = COALESCE(LOWER(?), '')
            LIMIT 1
            """,
            (
                transcript_id,
                item.get("text", ""),
                item.get("promised_by", ""),
                item.get("promised_to", ""),
            ),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """INSERT INTO promises (transcript_id, promised_by_name, promised_to_name, description, due_date)
            VALUES (?, ?, ?, ?, ?)""",
            (
                transcript_id,
                item.get("promised_by", ""),
                item.get("promised_to", ""),
                item.get("text", ""),
                item.get("due_date"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
