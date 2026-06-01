"""Relationship decay — detects cooling/neglected relationships.

For each person you've interacted with (via Slack or Gmail), compute:
- last_interaction: most recent Slack message or Gmail exchange
- days_since: days since last interaction
- recent_count: interactions in last 14 days
- prior_count: interactions in prior 14 days
- trend: "rising" / "stable" / "cooling" / "silent"

Flags people you care about who've gone quiet, without you noticing.
"""

import os
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()


def _slack_interaction_counts(since: datetime, until: datetime) -> dict[int, int]:
    """Count slack messages per canonical person in the given window."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT su.person_id AS pid, COUNT(*) AS c
            FROM slack_messages m
            JOIN slack_users su ON su.id = m.user_id
            WHERE su.person_id IS NOT NULL
              AND m.message_at >= ? AND m.message_at < ?
            GROUP BY su.person_id
            """,
            (since, until),
        ).fetchall()
    finally:
        conn.close()
    return {r["pid"]: r["c"] for r in rows}


def _gmail_interaction_counts(since: datetime, until: datetime) -> dict[int, int]:
    """Count gmail interactions (incoming + outgoing) per person in window."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT LOWER(from_email) AS email, COUNT(*) AS c
            FROM gmail_messages
            WHERE date >= ? AND date < ? AND from_email IS NOT NULL
            GROUP BY LOWER(from_email)
            """,
            (since, until),
        ).fetchall()
        emails = {r["email"]: r["c"] for r in rows}

        # Map emails to person_id
        if not emails:
            return {}
        placeholders = ",".join(["?"] * len(emails))
        rows = conn.execute(
            f"SELECT id, LOWER(email) AS email FROM people WHERE LOWER(email) IN ({placeholders})",
            list(emails.keys()),
        ).fetchall()
    finally:
        conn.close()
    return {r["id"]: emails[r["email"]] for r in rows}


def _last_interaction_per_person() -> dict[int, datetime]:
    """For every person, find the most recent slack or gmail touchpoint."""
    conn = get_connection()
    try:
        slack_rows = conn.execute(
            """
            SELECT su.person_id AS pid, MAX(m.message_at) AS t
            FROM slack_messages m
            JOIN slack_users su ON su.id = m.user_id
            WHERE su.person_id IS NOT NULL
            GROUP BY su.person_id
            """
        ).fetchall()
        gmail_rows = conn.execute(
            """
            SELECT p.id AS pid, MAX(g.date) AS t
            FROM gmail_messages g
            JOIN people p ON LOWER(p.email) = LOWER(g.from_email)
            GROUP BY p.id
            """
        ).fetchall()
    finally:
        conn.close()

    last: dict[int, datetime] = {}
    for r in slack_rows:
        if r["t"]:
            last[r["pid"]] = r["t"]
    for r in gmail_rows:
        if r["t"] and (r["pid"] not in last or r["t"] > last[r["pid"]]):
            last[r["pid"]] = r["t"]
    return last


def compute_relationship_decay(window_days: int = 14) -> dict:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=window_days)
    prior_start = now - timedelta(days=window_days * 2)

    slack_recent = _slack_interaction_counts(recent_start, now)
    slack_prior = _slack_interaction_counts(prior_start, recent_start)
    gmail_recent = _gmail_interaction_counts(recent_start, now)
    gmail_prior = _gmail_interaction_counts(prior_start, recent_start)
    last_touch = _last_interaction_per_person()

    # Get all known people
    conn = get_connection()
    try:
        people = conn.execute(
            "SELECT id, name, email, organization, is_self FROM people WHERE is_self IS NOT TRUE"
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for p in people:
        pid = p["id"]
        rcnt = slack_recent.get(pid, 0) + gmail_recent.get(pid, 0)
        pcnt = slack_prior.get(pid, 0) + gmail_prior.get(pid, 0)
        last = last_touch.get(pid)
        days_since = (now - last).days if last else None

        # Determine trend
        if rcnt == 0 and pcnt == 0 and days_since is None:
            continue  # never interacted
        if rcnt == 0 and pcnt == 0:
            trend = "silent"
        elif rcnt == 0 and pcnt > 0:
            trend = "cooling"
        elif pcnt == 0:
            trend = "new"
        elif rcnt > pcnt * 1.5:
            trend = "rising"
        elif rcnt < pcnt * 0.5:
            trend = "cooling"
        else:
            trend = "stable"

        entries.append({
            "person_id": pid,
            "name": p["name"],
            "email": p["email"],
            "organization": p["organization"] or "",
            "recent_count": rcnt,
            "prior_count": pcnt,
            "trend": trend,
            "last_interaction": last.isoformat() if last else None,
            "days_since": days_since,
        })

    # Sort: cooling + high prior first (lost relationships), then silent
    def sort_key(e):
        priority = {"cooling": 0, "silent": 1, "stable": 2, "rising": 3, "new": 4}.get(e["trend"], 5)
        return (priority, -e["prior_count"], e["days_since"] or 10000)

    entries.sort(key=sort_key)

    flagged = [e for e in entries if e["trend"] in ("cooling", "silent")]
    return {
        "window_days": window_days,
        "total_people": len(entries),
        "flagged_count": len(flagged),
        "flagged": flagged[:25],
        "rising": [e for e in entries if e["trend"] == "rising"][:10],
    }
