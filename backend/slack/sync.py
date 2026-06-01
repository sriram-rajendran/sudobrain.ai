"""Slack sync — fast direct API via Slack SDK.

Replaces the slow LLM-mediated MCP approach.
42 channels × ~1s = ~1 minute total instead of 84 minutes.
"""

import logging
import os
from datetime import datetime
from backend.slack import client as slack_client
from backend.slack import ingest
from backend.slack.schema import init_slack_tables
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.slack.sync")


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def sync_channels() -> dict:
    """Fetch and store all channels, mark excluded ones as disabled."""
    init_slack_tables()
    include_dms = _truthy_env("SUDOBRAIN_SLACK_INCLUDE_DMS", True)
    channels = slack_client.list_channels(exclude_archived=False, include_dms=include_dms)

    if not channels:
        return {"status": "empty", "channels": 0}

    enabled = 0
    excluded = 0

    conn = get_connection()
    try:
        if not include_dms:
            conn.execute(
                """
                UPDATE slack_channels
                SET sync_enabled = FALSE
                WHERE name LIKE 'dm:%' OR name LIKE 'mpdm-%'
                """
            )
        else:
            conn.execute(
                """
                UPDATE slack_channels
                SET sync_enabled = TRUE,
                    is_dm = TRUE
                WHERE is_archived = FALSE
                  AND (is_dm = TRUE OR name LIKE 'dm:%' OR name LIKE 'mpdm-%')
                """
            )
        conn.commit()
    finally:
        conn.close()

    for ch in channels:
        ingest.store_channel({
            "id": ch["id"],
            "name": ch.get("name", ""),
            "topic": ch.get("topic", {}).get("value", ""),
            "purpose": ch.get("purpose", {}).get("value", ""),
            "is_private": ch.get("is_private", False),
            "is_dm": ch.get("is_dm", False) or ch.get("is_im", False) or ch.get("is_mpim", False),
            "is_archived": ch.get("is_archived", False),
            "member_count": ch.get("num_members", 0),
        })

        if ch.get("is_archived") or slack_client.is_excluded_channel(ch.get("name", "")):
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE slack_channels SET sync_enabled = FALSE WHERE id = ?",
                    (ch["id"],),
                )
                conn.commit()
            finally:
                conn.close()
            excluded += 1
        else:
            enabled += 1

    dm_count = sum(1 for ch in channels if ch.get("is_dm") or ch.get("is_im") or ch.get("is_mpim"))
    logger.info("Channels: %d enabled, %d excluded, %d DMs visible", enabled, excluded, dm_count)
    return {
        "status": "completed",
        "channels": len(channels),
        "enabled": enabled,
        "excluded": excluded,
        "dms": dm_count,
    }


def sync_users() -> dict:
    """Fetch all users and link to people graph."""
    init_slack_tables()
    users = slack_client.list_users()

    for u in users:
        ingest.store_user(u)

    logger.info("Slack users: %d synced", len(users))
    return {"status": "completed", "users": len(users)}


def _build_users_cache() -> dict:
    """Build a user_id -> user_info dict for name resolution."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, real_name, email FROM slack_users"
        ).fetchall()
        cache = {}
        for r in rows:
            cache[r["id"]] = {
                "name": r["name"],
                "real_name": r["real_name"],
                "email": r["email"],
            }
        return cache
    finally:
        conn.close()


def sync_channel_messages(channel_id: str, channel_name: str = "",
                          days: int = 30, limit: int = 100,
                          users_cache: dict = None,
                          extract_knowledge: bool = True) -> dict:
    """Sync messages from a single channel via direct API."""
    init_slack_tables()

    if users_cache is None:
        users_cache = _build_users_cache()

    # Log sync start
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO slack_sync_log (channel_id, channel_name, status) VALUES (?, ?, 'running')",
            (channel_id, channel_name),
        )
        log_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    try:
        # Fetch messages — fast direct API
        raw_messages = slack_client.fetch_channel_messages(
            channel_id, channel_name=channel_name, days=days, limit=limit
        )

        stored = 0
        threads_fetched = 0

        for raw_msg in raw_messages:
            if raw_msg.get("subtype") in slack_client.SYSTEM_MESSAGE_SUBTYPES:
                continue

            msg = slack_client.format_message(raw_msg, users_cache)
            ingest.store_message(channel_id, msg)
            stored += 1

            # Fetch thread replies
            if raw_msg.get("reply_count", 0) > 0:
                replies = slack_client.fetch_thread_replies(channel_id, raw_msg["ts"])
                for reply in replies:
                    if reply.get("subtype") not in slack_client.SYSTEM_MESSAGE_SUBTYPES:
                        reply_msg = slack_client.format_message(reply, users_cache)
                        reply_msg["thread_ts"] = raw_msg["ts"]
                        ingest.store_message(channel_id, reply_msg)
                threads_fetched += 1

        extracted = ingest.extract_from_messages(channel_id) if extract_knowledge else 0

        # Update sync log
        conn = get_connection()
        try:
            conn.execute("""
                UPDATE slack_sync_log
                SET messages_fetched = ?, threads_fetched = ?, knowledge_extracted = ?,
                    status = 'completed', completed_at = ?
                WHERE id = ?
            """, (stored, threads_fetched, extracted, datetime.now().isoformat(), log_id))
            conn.execute(
                "UPDATE slack_channels SET last_synced_at = ? WHERE id = ?",
                (datetime.now().isoformat(), channel_id),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("#%s: %d msgs, %d threads, %d extracted", channel_name, stored, threads_fetched, extracted)
        return {
            "channel": channel_name or channel_id,
            "messages": stored,
            "threads": threads_fetched,
            "extracted": extracted,
            "status": "completed",
        }

    except Exception as e:
        logger.error("Sync failed for #%s: %s", channel_name, e)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE slack_sync_log SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                (str(e)[:500], datetime.now().isoformat(), log_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {"channel": channel_name or channel_id, "status": "failed", "error": str(e)}


def sync_all(channel_filter: list[str] = None, messages_per_channel: int = 100,
             days: int = 30, extract_knowledge: bool = True) -> dict:
    """Sync all enabled channels. Fast — uses direct Slack API."""
    init_slack_tables()

    # Ensure channels are loaded
    conn = get_connection()
    try:
        ch_count = conn.execute(
            "SELECT COUNT(*) as c FROM slack_channels WHERE sync_enabled = TRUE AND is_archived = FALSE"
        ).fetchone()["c"]
    finally:
        conn.close()

    if ch_count == 0:
        logger.info("No channels found, syncing channel list first...")
        sync_channels()

    # Build user cache once for all channels
    conn = get_connection()
    try:
        if channel_filter:
            placeholders = ",".join("?" * len(channel_filter))
            rows = conn.execute(
                f"SELECT id, name FROM slack_channels WHERE sync_enabled = TRUE AND is_archived = FALSE AND name IN ({placeholders})",
                channel_filter,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name FROM slack_channels WHERE sync_enabled = TRUE AND is_archived = FALSE ORDER BY name"
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"status": "no_channels", "channels_synced": 0, "results": []}

    # Sync users first for name resolution
    if not _build_users_cache():
        sync_users()
    users_cache = _build_users_cache()

    logger.info("Syncing %d channels via direct Slack API...", len(rows))
    results = []
    total_messages = 0
    total_extracted = 0

    for r in rows:
        result = sync_channel_messages(
            r["id"], r["name"],
            days=days,
            limit=messages_per_channel,
            users_cache=users_cache,
            extract_knowledge=extract_knowledge,
        )
        results.append(result)
        total_messages += result.get("messages", 0)
        total_extracted += result.get("extracted", 0)

    logger.info(
        "Slack sync complete: %d channels, %d messages, %d extracted",
        len(results), total_messages, total_extracted,
    )

    return {
        "status": "completed",
        "channels_synced": len(results),
        "total_messages": total_messages,
        "total_extracted": total_extracted,
        "results": results,
    }


def get_sync_status() -> dict:
    """Get current sync stats."""
    init_slack_tables()
    conn = get_connection()
    try:
        channels = conn.execute("SELECT COUNT(*) as c FROM slack_channels").fetchone()["c"]
        messages = conn.execute("SELECT COUNT(*) as c FROM slack_messages").fetchone()["c"]
        extracted = conn.execute("SELECT COUNT(*) as c FROM slack_messages WHERE extracted = TRUE").fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) as c FROM slack_users").fetchone()["c"]
        last = conn.execute("SELECT MAX(completed_at) as d FROM slack_sync_log WHERE status = 'completed'").fetchone()
        return {
            "channels": channels,
            "messages": messages,
            "messages_extracted": extracted,
            "users": users,
            "last_sync": last["d"] if last else None,
        }
    finally:
        conn.close()
