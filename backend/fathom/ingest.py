"""Lightweight Fathom ingestion (no audio download, no Sarvam).

Uses Fathom's pre-existing transcripts and metadata directly:
- pulls meetings via list_meetings(include_transcript, include_action_items, include_summary)
- creates a recording row with mode='fathom_meeting'
- creates a transcript row with the transcript text
- inserts speaker segments
- runs knowledge extraction so action_items / decisions / promises populate

Idempotent — skips meetings already ingested.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from backend.storage.database import get_connection
from backend.fathom.client import list_meetings, _timestamp_to_seconds

logger = logging.getLogger("sudobrain.fathom.ingest")


def _existing_recording_ids() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM recordings WHERE id LIKE 'fathom_%'"
        ).fetchall()
        return {r["id"] for r in rows}
    finally:
        conn.close()


def _build_transcript_text(meeting: dict) -> str:
    """Concatenate Fathom transcript entries into a flat text block."""
    transcript = meeting.get("transcript")
    if not transcript:
        return ""
    if isinstance(transcript, str):
        return transcript
    lines = []
    for entry in transcript:
        speaker = (entry.get("speaker") or {}).get("display_name", "Unknown")
        text = entry.get("text", "")
        ts = entry.get("timestamp", "")
        if text:
            lines.append(f"[{ts}] {speaker}: {text}")
    return "\n".join(lines)


def _build_segments(meeting: dict) -> list[dict]:
    """Convert Fathom transcript entries to segment dicts."""
    transcript = meeting.get("transcript")
    if not transcript or not isinstance(transcript, list):
        return []
    out = []
    for i, entry in enumerate(transcript):
        speaker = (entry.get("speaker") or {}).get("display_name", "Unknown")
        text = entry.get("text", "")
        ts = entry.get("timestamp", "")
        start = _timestamp_to_seconds(ts) if ts else float(i)
        if not text:
            continue
        out.append({
            "speaker_id": speaker,
            "speaker_label": speaker,
            "start_seconds": start,
            "end_seconds": start + 5,
            "text": text,
            "language": "en",
        })
    return out


def _participants_from_meeting(m: dict) -> list[dict]:
    invitees = m.get("calendar_invitees") or []
    out = []
    for i in invitees:
        out.append({
            "name": i.get("name", ""),
            "email": (i.get("email") or "").lower(),
            "is_external": i.get("is_external", False),
        })
    return out


def store_meeting(meeting: dict) -> str | None:
    """Store a single Fathom meeting → recording + transcript + segments.

    Returns recording_id, or None if already exists / no usable content.
    """
    rid = str(meeting.get("recording_id", ""))
    if not rid:
        return None
    rec_id = f"fathom_{rid}"

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM recordings WHERE id = ?", (rec_id,)
        ).fetchone()
        if existing:
            return None

        # Compute duration
        start = meeting.get("recording_start_time") or meeting.get("scheduled_start_time")
        end = meeting.get("recording_end_time") or meeting.get("scheduled_end_time")
        duration_seconds = 0
        if start and end:
            try:
                s = datetime.fromisoformat(start.replace("Z", "+00:00"))
                e = datetime.fromisoformat(end.replace("Z", "+00:00"))
                duration_seconds = int((e - s).total_seconds())
            except Exception:
                pass

        title = meeting.get("title") or meeting.get("meeting_title") or "Fathom meeting"
        share_url = meeting.get("share_url") or meeting.get("url") or ""
        created = meeting.get("created_at")
        if created:
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                created = datetime.now(timezone.utc)
        else:
            created = datetime.now(timezone.utc)

        conn.execute(
            """
            INSERT INTO recordings
            (id, mode, created_at, duration_seconds, audio_path, status)
            VALUES (?, ?, ?, ?, ?, 'completed')
            """,
            (
                rec_id,
                "fathom_meeting",
                created.replace(tzinfo=None),
                duration_seconds,
                share_url,
            ),
        )

        full_text = _build_transcript_text(meeting)
        if not full_text:
            full_text = (meeting.get("default_summary") or "")[:5000]

        participants = _participants_from_meeting(meeting)
        transcript_id = f"fathom_t_{rid}"
        transcript_blob = {
            "id": transcript_id,
            "recording_id": rec_id,
            "source": "fathom",
            "fathom": {"fathom_recording_id": rid, "share_url": share_url},
            "title": title,
            "created_at": created.isoformat(),
            "duration_seconds": duration_seconds,
            "language": {"primary": "en", "detected": ["en"], "is_code_mixed": False},
            "participants": participants,
            "segments": _build_segments(meeting),
            "full_transcript": full_text,
            "processing": {
                "engine": "fathom",
                "model": "fathom",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "audio_preprocessing": [],
            },
        }

        conn.execute(
            """
            INSERT INTO transcripts
            (id, recording_id, full_text, primary_language, is_code_mixed,
             engine, processed_at, transcript_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transcript_id,
                rec_id,
                full_text,
                "en",
                False,
                "fathom",
                datetime.now(timezone.utc).replace(tzinfo=None),
                json.dumps(transcript_blob),
            ),
        )

        # Insert segments
        for seg in transcript_blob["segments"]:
            conn.execute(
                """
                INSERT INTO segments
                (transcript_id, speaker_id, speaker_label, start_seconds, end_seconds, text, language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript_id,
                    seg["speaker_id"],
                    seg["speaker_label"],
                    seg["start_seconds"],
                    seg["end_seconds"],
                    seg["text"],
                    seg["language"],
                ),
            )

        # Save Fathom-provided action items if present
        actions = meeting.get("action_items") or []
        for a in actions:
            text = a.get("text") or a.get("description") or ""
            if not text:
                continue
            assignee = (a.get("assignee") or {}).get("name", "") if isinstance(a.get("assignee"), dict) else (a.get("assignee") or "")
            due = a.get("due_date")
            conn.execute(
                """
                INSERT INTO action_items (transcript_id, text, assignee, due_date, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (transcript_id, text, assignee, due),
            )

        conn.commit()
        return rec_id
    finally:
        conn.close()


def sync_recent(days_back: int = 60, limit: int = 25, run_extract: bool = True) -> dict:
    """Sync up to `limit` meetings created in the last `days_back` days.

    Calls list_meetings with include_transcript so we don't need a 2nd API call.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = list_meetings(
        limit=limit,
        include_transcript=True,
        include_summary=True,
        include_action_items=True,
        created_after=cutoff,
    )
    items = resp.get("items", [])

    stored = []
    skipped = 0
    for m in items:
        rid = store_meeting(m)
        if rid:
            stored.append(rid)
        else:
            skipped += 1

    extracted_count = 0
    if run_extract and stored:
        from backend.ai.local_llm_engine import extract_knowledge
        from backend.graph.neo4j_client import ingest_knowledge
        from backend.storage import database as db

        for rec_id in stored:
            try:
                conn = get_connection()
                t_row = conn.execute(
                    "SELECT id, full_text FROM transcripts WHERE recording_id = ? LIMIT 1",
                    (rec_id,),
                ).fetchone()
                conn.close()
                if not t_row or not t_row["full_text"]:
                    continue

                k = extract_knowledge(t_row["full_text"][:20000])
                if not k:
                    continue
                tid = t_row["id"]
                for it in k.get("action_items", []):
                    db.save_action_item(
                        transcript_id=tid,
                        text=it.get("text", ""),
                        assignee=it.get("assignee"),
                        project=k.get("project"),
                        due_date=it.get("due_date"),
                    )
                for it in k.get("decisions", []):
                    db.save_decision(
                        transcript_id=tid,
                        text=it.get("text", ""),
                        made_by=it.get("made_by"),
                        context=it.get("context"),
                        project=k.get("project"),
                    )
                for it in k.get("promises", []):
                    text = it.get("text", "")
                    if not text:
                        continue
                    pconn = get_connection()
                    try:
                        existing = pconn.execute(
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
                                tid,
                                text,
                                it.get("promised_by") or "",
                                it.get("promised_to") or "",
                            ),
                        ).fetchone()
                        if existing:
                            continue
                        pconn.execute(
                            """
                            INSERT INTO promises
                            (transcript_id, promised_by_name, promised_to_name, description, due_date, status)
                            VALUES (?, ?, ?, ?, ?, 'pending')
                            """,
                            (
                                tid,
                                it.get("promised_by") or "",
                                it.get("promised_to") or "",
                                text,
                                it.get("due_date"),
                            ),
                        )
                        pconn.commit()
                    finally:
                        pconn.close()
                try:
                    ingest_knowledge(k, tid, participants=[])
                except Exception:
                    pass
                extracted_count += 1
            except Exception as e:
                logger.warning("extract failed for %s: %s", rec_id, e)

    return {
        "total_meetings": len(items),
        "stored": len(stored),
        "skipped_existing": skipped,
        "extracted": extracted_count,
        "stored_ids": stored,
    }
