"""Slack client — Direct Slack SDK.

Uses a user token with read scopes. No bot is visible to the team. READ-ONLY.

"""

import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sudobrain.slack.client")

SLACK_USER_TOKEN = os.getenv("SLACK_USER_TOKEN", "")

# Channels to exclude from sync
EXCLUDED_CHANNEL_PATTERNS = [
    "alerts", "alert", "bot", "notifications", "github",
    "ci-cd", "cicd", "deployments", "deploy", "monitoring",
    "error", "errors", "logs", "tracking",
    "updates", "notification",
    "pagerduty", "opsgenie", "zapier", "datadog",
    "jira", "calendar", "drive",
    "system-notifications", "prod-user-events",
    "user-events", "auth-events", "login-alerts", "prefiled-bills-alert",
    "slackbot",
    "access-requests", "pipeline", "weekly-upload",
]

SYSTEM_MESSAGE_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_name",
    "channel_purpose",
    "channel_topic",
    "channel_archive",
    "channel_unarchive",
    "message_deleted",
    "message_changed",
    "pinned_item",
}


def _get_client():
    """Get authenticated Slack WebClient."""
    from slack_sdk import WebClient
    token = SLACK_USER_TOKEN or os.getenv("SLACK_USER_TOKEN", "")
    if not token:
        raise ValueError("SLACK_USER_TOKEN not set in .env")
    return WebClient(token=token)


def is_available() -> bool:
    """Check if Slack token is configured and valid."""
    try:
        client = _get_client()
        client.auth_test()
        return True
    except Exception:
        return False


def is_excluded_channel(channel_name: str) -> bool:
    """Check if channel should be excluded from sync."""
    name = (channel_name or "").lower().strip()
    return any(pattern in name for pattern in EXCLUDED_CHANNEL_PATTERNS)


def list_channels(exclude_archived: bool = True,
                  include_dms: bool = False) -> list[dict]:
    """List all channels + DMs accessible to the user.

    DMs (im) and group DMs (mpim) are included by default. DMs lack a
    human-readable name, so we synthesize one from the counterpart user.
    """
    try:
        client = _get_client()
        all_channels = []
        cursor = None

        types = "public_channel,private_channel"
        if include_dms:
            types += ",mpim,im"

        while True:
            resp = client.conversations_list(
                types=types,
                limit=200,
                cursor=cursor,
                exclude_archived=exclude_archived,
            )
            all_channels.extend(resp["channels"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        # Build a user-id -> display-name map for DM labeling (from DB cache)
        user_map: dict[str, str] = {}
        if include_dms and any(c.get("is_im") for c in all_channels):
            try:
                from backend.storage.database import get_connection
                conn = get_connection()
                try:
                    for row in conn.execute(
                        "SELECT id, name, real_name FROM slack_users"
                    ).fetchall():
                        user_map[row["id"]] = (
                            row["real_name"] or row["name"] or row["id"]
                        )
                finally:
                    conn.close()
            except Exception as e:
                logger.debug("user map fetch failed: %s", e)

        for c in all_channels:
            if c.get("is_im"):
                other = c.get("user") or ""
                c["name"] = f"dm:{user_map.get(other, other)}"
                c["is_private"] = True
                c["is_dm"] = True
            elif c.get("is_mpim"):
                c.setdefault("name", f"mpim:{c['id']}")
                c["is_private"] = True
                c["is_dm"] = True

        logger.info("Slack: found %d channels (incl DMs=%s)",
                    len(all_channels), include_dms)
        return all_channels

    except Exception as e:
        logger.error("list_channels failed: %s", e)
        return []


def fetch_channel_messages(channel_id: str, channel_name: str = "",
                           days: int = 30, limit: int = 100) -> list[dict]:
    """Fetch recent messages from a channel. Fast direct API call.

    Auto-halves page size on IncompleteRead so a single oversized payload
    doesn't block the whole channel.
    """
    from datetime import datetime, timedelta
    from http.client import IncompleteRead

    client = _get_client()
    oldest = str((datetime.now() - timedelta(days=days)).timestamp())

    all_messages: list[dict] = []
    cursor = None
    page_size = min(limit, 200)

    while len(all_messages) < limit:
        try:
            resp = client.conversations_history(
                channel=channel_id,
                oldest=oldest,
                limit=page_size,
                cursor=cursor,
            )
        except (IncompleteRead, Exception) as e:
            is_incomplete = "IncompleteRead" in type(e).__name__ or "IncompleteRead" in str(e)
            if is_incomplete and page_size > 10:
                page_size = max(10, page_size // 2)
                logger.warning("Slack #%s: IncompleteRead, retry with page_size=%d",
                               channel_name, page_size)
                continue
            logger.warning("fetch_channel_messages failed for #%s: %s", channel_name, e)
            break

        msgs = resp.get("messages", [])
        all_messages.extend(msgs)
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor or not resp.get("has_more"):
            break

    logger.debug("Slack: fetched %d messages from #%s", len(all_messages), channel_name)
    return all_messages[:limit]


def fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """Fetch replies in a thread."""
    try:
        client = _get_client()
        resp = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=100,
        )
        replies = resp.get("messages", [])
        # Skip the parent message (first item)
        return replies[1:] if len(replies) > 1 else []

    except Exception as e:
        logger.debug("fetch_thread_replies failed: %s", e)
        return []


def get_user_info(user_id: str) -> dict:
    """Get user profile info."""
    try:
        client = _get_client()
        resp = client.users_info(user=user_id)
        user = resp.get("user", {})
        profile = user.get("profile", {})
        return {
            "id": user_id,
            "name": user.get("name", ""),
            "real_name": profile.get("real_name", ""),
            "email": profile.get("email", ""),
            "title": profile.get("title", ""),
            "is_bot": user.get("is_bot", False),
        }
    except Exception as e:
        logger.debug("get_user_info failed for %s: %s", user_id, e)
        return {"id": user_id}


def list_users() -> list[dict]:
    """List all workspace users. Auto-halves page size on IncompleteRead."""
    client = _get_client()
    all_users: list[dict] = []
    cursor = None
    page_size = 200

    while True:
        try:
            resp = client.users_list(limit=page_size, cursor=cursor)
        except Exception as e:
            if "IncompleteRead" in type(e).__name__ or "IncompleteRead" in str(e):
                if page_size > 20:
                    page_size = max(20, page_size // 2)
                    logger.warning("list_users: IncompleteRead, retry page_size=%d", page_size)
                    continue
            logger.error("list_users failed: %s", e)
            return all_users

        for u in resp.get("members", []):
            if u.get("deleted") or u.get("is_bot") or u.get("id") == "USLACKBOT":
                continue
            profile = u.get("profile", {})
            all_users.append({
                "id": u["id"],
                "name": u.get("name", ""),
                "real_name": profile.get("real_name", ""),
                "email": profile.get("email", ""),
                "title": profile.get("title", ""),
                "is_bot": u.get("is_bot", False),
            })

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info("Slack: found %d users", len(all_users))
    return all_users


def format_message(msg: dict, users_cache: dict = None) -> dict:
    """Convert raw Slack message to our standard format."""
    user_id = msg.get("user", "")
    user_name = ""

    if users_cache and user_id in users_cache:
        user_name = users_cache[user_id].get("real_name") or users_cache[user_id].get("name", "")
    if not user_name:
        user_name = (
            msg.get("username")
            or (msg.get("bot_profile") or {}).get("name")
            or user_id
        )

    text = msg.get("text", "")
    reactions = msg.get("reactions", [])
    reaction_count = sum(r.get("count", 0) for r in reactions)
    reply_count = msg.get("reply_count", 0)

    files = []
    for f in msg.get("files", []) or []:
        if not isinstance(f, dict):
            continue
        files.append({
            "id": f.get("id"),
            "name": f.get("name") or f.get("title", ""),
            "filetype": (f.get("filetype") or "").lower(),
            "mimetype": f.get("mimetype", ""),
            "size": f.get("size", 0),
            "url_private": f.get("url_private"),
            "url_private_download": f.get("url_private_download"),
        })

    return {
        "ts": msg.get("ts", ""),
        "user_id": user_id,
        "user_name": user_name or user_id,
        "text": text,
        "thread_ts": msg.get("thread_ts"),
        "reply_count": reply_count,
        "reaction_count": reaction_count,
        "reactions": [{"emoji": r["name"], "users": r.get("users", [])} for r in reactions],
        "mention_users": [],
        "is_bot": bool(msg.get("bot_id") or msg.get("subtype") == "bot_message"),
        "files": files,
    }


def download_slack_file(url_private_download: str) -> bytes:
    """Download a Slack file (requires files:read scope). Returns bytes or b''."""
    import os
    import requests
    token = os.getenv("SLACK_USER_TOKEN", "")
    if not token or not url_private_download:
        return b""
    try:
        r = requests.get(
            url_private_download,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.debug("download_slack_file failed: %s", e)
        return b""
