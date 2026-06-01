"""Backfill ChromaDB with Slack messages, Gmail emails, Linear issues,
extracted action_items / decisions / promises, and attachment text."""

import logging
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("backfill_vectors")

from backend.storage.database import get_connection
from backend.storage.chroma_store import add_batch, count


def backfill():
    conn = get_connection()
    total = 0
    try:
        # Slack messages (extractable ones with real text)
        rows = conn.execute(
            "SELECT id, text, channel_id, user_name, message_at FROM slack_messages "
            "WHERE length(text) > 15 AND is_bot_message = FALSE"
        ).fetchall()
        batch = [{
            "id": f"slack_msg_{r['id']}",
            "text": r["text"],
            "metadata": {
                "source": "slack",
                "channel_id": r["channel_id"] or "",
                "user": r["user_name"] or "",
                "date": str(r["message_at"])[:10] if r["message_at"] else "",
            },
        } for r in rows]
        if batch:
            # chunk into groups of 500 to keep memory + HTTP payload reasonable
            for i in range(0, len(batch), 500):
                add_batch(batch[i:i+500])
            total += len(batch)
        logger.info("slack: %d", len(batch))

        # Gmail messages
        rows = conn.execute(
            "SELECT id, subject, from_email, body, date FROM gmail_messages "
            "WHERE length(body) > 20"
        ).fetchall()
        batch = [{
            "id": f"gmail_{r['id']}",
            "text": f"{r['subject'] or ''}\n{r['body'][:3000]}",
            "metadata": {
                "source": "gmail",
                "from": r["from_email"] or "",
                "date": str(r["date"])[:10] if r["date"] else "",
            },
        } for r in rows]
        if batch:
            for i in range(0, len(batch), 200):
                add_batch(batch[i:i+200])
            total += len(batch)
        logger.info("gmail: %d", len(batch))

        # Gmail attachments with extracted text
        rows = conn.execute(
            "SELECT message_id, filename, extracted_text FROM gmail_attachments "
            "WHERE char_count > 100"
        ).fetchall()
        batch = [{
            "id": f"gmail_att_{r['message_id']}_{r['filename']}",
            "text": f"{r['filename']}\n{r['extracted_text'][:5000]}",
            "metadata": {"source": "gmail_attachment", "filename": r["filename"]},
        } for r in rows]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("gmail attachments: %d", len(batch))

        # Slack files with extracted text
        rows = conn.execute(
            "SELECT id, filename, filetype, extracted_text FROM slack_files "
            "WHERE char_count > 100"
        ).fetchall()
        batch = [{
            "id": f"slack_file_{r['id']}",
            "text": f"{r['filename']}\n{r['extracted_text'][:5000]}",
            "metadata": {"source": "slack_file", "filetype": r["filetype"] or ""},
        } for r in rows]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("slack files: %d", len(batch))

        # Linear issues (title + description)
        rows = conn.execute(
            "SELECT id, title, description, state_name, project_name, assignee_name FROM linear_issues"
        ).fetchall()
        batch = [{
            "id": f"linear_{r['id']}",
            "text": f"{r['title']}\n{r['description'] or ''}",
            "metadata": {
                "source": "linear",
                "state": r["state_name"] or "",
                "project": r["project_name"] or "",
                "assignee": r["assignee_name"] or "",
            },
        } for r in rows]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("linear: %d", len(batch))

        # Action items
        rows = conn.execute(
            "SELECT id, text, assignee, project FROM action_items"
        ).fetchall()
        batch = [{
            "id": f"action_{r['id']}",
            "text": r["text"],
            "metadata": {
                "source": "action_item",
                "assignee": r["assignee"] or "",
                "project": r["project"] or "",
            },
        } for r in rows if r["text"]]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("action_items: %d", len(batch))

        # Decisions
        rows = conn.execute(
            "SELECT id, text, made_by, project FROM decisions"
        ).fetchall()
        batch = [{
            "id": f"decision_{r['id']}",
            "text": r["text"],
            "metadata": {
                "source": "decision",
                "made_by": r["made_by"] or "",
                "project": r["project"] or "",
            },
        } for r in rows if r["text"]]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("decisions: %d", len(batch))

        # Promises
        rows = conn.execute(
            "SELECT id, description, promised_by_name, promised_to_name FROM promises"
        ).fetchall()
        batch = [{
            "id": f"promise_{r['id']}",
            "text": r["description"],
            "metadata": {
                "source": "promise",
                "by": r["promised_by_name"] or "",
                "to": r["promised_to_name"] or "",
            },
        } for r in rows if r["description"]]
        if batch:
            add_batch(batch)
            total += len(batch)
        logger.info("promises: %d", len(batch))

    finally:
        conn.close()

    logger.info("total backfilled: %d, chroma count now: %d", total, count())


if __name__ == "__main__":
    backfill()
