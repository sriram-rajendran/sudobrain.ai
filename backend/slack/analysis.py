"""Slack analysis — pending items, channel health, engagement metrics."""

import json
import logging
from datetime import datetime, timedelta
from backend.storage.database import get_connection
from backend.slack.schema import init_slack_tables

logger = logging.getLogger("sudobrain.slack.analysis")


def get_pending_items() -> dict:
    """Get pending items from Slack.

    - Unanswered questions (messages ending in ? with no replies after 24h)
    - Unanswered @-mentions (@user messages with no response)
    - Stale threads (discussions that died without resolution)
    """
    init_slack_tables()
    conn = get_connection()
    try:
        # Unanswered questions
        questions = conn.execute("""
            SELECT m.id, m.text, m.user_name, m.ts, c.name as channel_name
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.text LIKE '%?%'
              AND m.reply_count = 0
              AND m.is_bot_message = FALSE
              AND LENGTH(m.text) > 20
              AND LENGTH(m.text) < 500
            ORDER BY m.ts DESC
            LIMIT 20
        """).fetchall()

        # Messages with mentions but no reply
        mentions = conn.execute("""
            SELECT m.id, m.text, m.user_name, m.ts, m.mention_users, c.name as channel_name
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.mention_users IS NOT NULL
              AND m.reply_count = 0
              AND m.is_bot_message = FALSE
            ORDER BY m.ts DESC
            LIMIT 20
        """).fetchall()

        # Stale threads — threads with <=2 replies and no activity in 7+ days
        one_week = (datetime.now() - timedelta(days=7)).timestamp()
        stale_threads = conn.execute("""
            SELECT m.id, m.text, m.user_name, m.ts, m.reply_count, c.name as channel_name
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.is_thread_parent = TRUE
              AND m.reply_count <= 2
              AND CAST(m.ts AS DOUBLE PRECISION) < ?
              AND m.is_bot_message = FALSE
            ORDER BY m.ts DESC
            LIMIT 10
        """, (str(one_week),)).fetchall()

    finally:
        conn.close()

    return {
        "unanswered_questions": [dict(r._row) for r in questions],
        "unanswered_mentions": [dict(r._row) for r in mentions],
        "stale_threads": [dict(r._row) for r in stale_threads],
        "total": len(questions) + len(mentions) + len(stale_threads),
    }


def get_channel_health() -> list[dict]:
    """Get health metrics per channel."""
    init_slack_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                c.id,
                c.name,
                c.member_count,
                COUNT(m.id) as total_messages,
                COUNT(CASE WHEN m.reply_count > 0 THEN 1 END) as threaded_messages,
                COUNT(CASE WHEN m.text LIKE '%?%' THEN 1 END) as questions,
                COUNT(CASE WHEN m.text LIKE '%?%' AND m.reply_count = 0 THEN 1 END) as unanswered_questions,
                COUNT(DISTINCT m.user_id) as unique_speakers,
                MAX(m.ts) as last_activity
            FROM slack_channels c
            LEFT JOIN slack_messages m ON m.channel_id = c.id AND m.is_bot_message = FALSE
            WHERE c.sync_enabled = TRUE
            GROUP BY c.id, c.name, c.member_count
            ORDER BY total_messages DESC
        """).fetchall()

        results = []
        for r in rows:
            data = dict(r._row)
            total = data.get("total_messages", 0)
            questions = data.get("questions", 0)
            unanswered = data.get("unanswered_questions", 0)

            # Health score: activity + answer rate - unanswered penalty
            if total > 0:
                answer_rate = ((questions - unanswered) / questions * 100) if questions > 0 else 100
                data["answer_rate"] = round(answer_rate)
                if total > 10 and answer_rate < 50:
                    data["health"] = "poor"
                elif total > 5:
                    data["health"] = "good"
                else:
                    data["health"] = "quiet"
            else:
                data["answer_rate"] = 0
                data["health"] = "inactive"

            results.append(data)

        return results
    finally:
        conn.close()


def get_engagement_metrics(days: int = 30) -> dict:
    """Get engagement metrics across all channels."""
    init_slack_tables()
    conn = get_connection()
    try:
        # Top message senders
        top_senders = conn.execute("""
            SELECT user_name, user_id, COUNT(*) as message_count
            FROM slack_messages
            WHERE is_bot_message = FALSE
              AND user_name IS NOT NULL
            GROUP BY user_id, user_name
            ORDER BY message_count DESC
            LIMIT 10
        """).fetchall()

        # Most active channels
        active_channels = conn.execute("""
            SELECT c.name, COUNT(m.id) as count
            FROM slack_messages m
            JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.is_bot_message = FALSE
            GROUP BY c.id, c.name
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()

        # Total stats
        totals = conn.execute("""
            SELECT
                COUNT(*) as total_messages,
                COUNT(DISTINCT user_id) as total_users,
                COUNT(DISTINCT channel_id) as total_channels,
                COUNT(CASE WHEN reply_count > 0 THEN 1 END) as threads
            FROM slack_messages
            WHERE is_bot_message = FALSE
        """).fetchone()

        return {
            "period_days": days,
            "totals": dict(totals._row) if totals else {},
            "top_senders": [dict(r._row) for r in top_senders],
            "most_active_channels": [dict(r._row) for r in active_channels],
        }
    finally:
        conn.close()


def get_conversation_summary(channel_id: str, limit: int = 50) -> dict:
    """Generate a high-level summary of recent conversation in a channel."""
    from backend.ai.local_llm_engine import ask

    init_slack_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT user_name, text, ts
            FROM slack_messages
            WHERE channel_id = ?
              AND is_bot_message = FALSE
              AND LENGTH(text) > 10
            ORDER BY ts DESC
            LIMIT ?
        """, (channel_id, limit)).fetchall()

        ch_row = conn.execute(
            "SELECT name FROM slack_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        channel_name = ch_row["name"] if ch_row else channel_id
    finally:
        conn.close()

    if not rows:
        return {"channel": channel_name, "summary": "No messages to summarize"}

    conversation = "\n".join(
        f"{r['user_name']}: {r['text']}" for r in reversed(rows)
    )[:5000]

    prompt = f"""Summarize this Slack conversation from #{channel_name}.

Format:
**Topics discussed:**
- (bullet list)

**Key decisions:**
- (if any)

**Open questions:**
- (if any)

**People involved:**
- (list)

Keep it under 150 words.

Conversation:
{conversation}"""

    summary = ask(prompt, max_wait=60)
    return {
        "channel": channel_name,
        "channel_id": channel_id,
        "message_count": len(rows),
        "summary": summary,
    }
