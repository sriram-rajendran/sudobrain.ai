"""Focus / fragmentation index.

Daily score: how fragmented was your day?

Factors (per day, based on your slack message times + calendar events if available):
- messages_count:         total messages you sent
- context_switches:       gaps >= 30 min between messages + different-channel bursts
- deep_work_block_min:    longest gap between messages (minutes, capped at 180)
- meeting_density:        calendar events per hour during working hours
- late_night_ratio:       messages sent after 22:00 IST / before 07:00 IST

Composite focus_score: 0-100 where 100 = single-threaded deep focus, 0 = constant fragmentation.
"""

import os
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()


def _self_slack_uid() -> str | None:
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT su.id FROM slack_users su "
            "JOIN people p ON p.id = su.person_id "
            "WHERE LOWER(p.email) = ? LIMIT 1",
            (SELF_EMAIL,),
        ).fetchone()
        return r["id"] if r else None
    finally:
        conn.close()


def _daily_focus(uid: str, day_date: datetime) -> dict:
    """Compute focus stats for a single day (IST-aligned)."""
    conn = get_connection()
    try:
        # Messages in this IST day
        rows = conn.execute(
            """
            SELECT channel_id, message_at AT TIME ZONE 'Asia/Kolkata' AS ist_time
            FROM slack_messages
            WHERE user_id = ?
              AND DATE(message_at AT TIME ZONE 'Asia/Kolkata') = ?
            ORDER BY message_at ASC
            """,
            (uid, day_date.date()),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "date": day_date.date().isoformat(),
            "messages": 0,
            "channels_touched": 0,
            "context_switches": 0,
            "longest_gap_minutes": 0,
            "late_night_messages": 0,
            "focus_score": None,
        }

    times = [r["ist_time"] for r in rows]
    channels = [r["channel_id"] for r in rows]

    # Context switches: channel changes OR gaps >= 30 min
    switches = 0
    longest_gap = 0
    late_night = 0
    for i, t in enumerate(times):
        if t.hour >= 22 or t.hour < 7:
            late_night += 1
        if i > 0:
            gap = (t - times[i - 1]).total_seconds() / 60
            longest_gap = max(longest_gap, gap)
            if gap >= 30 or channels[i] != channels[i - 1]:
                switches += 1

    msgs = len(times)
    unique_channels = len(set(channels))
    # Normalize: fewer switches per message = more focus
    switches_per_msg = switches / msgs if msgs else 0
    deep_block_score = min(100, longest_gap / 1.8)  # 180 min = 100
    switch_score = max(0, 100 - switches_per_msg * 100)
    late_penalty = min(40, late_night * 5)

    focus_score = max(0, min(100, round(
        (deep_block_score * 0.5 + switch_score * 0.5) - late_penalty, 1
    )))

    return {
        "date": day_date.date().isoformat(),
        "messages": msgs,
        "channels_touched": unique_channels,
        "context_switches": switches,
        "longest_gap_minutes": round(longest_gap),
        "late_night_messages": late_night,
        "focus_score": focus_score,
    }


def compute_focus_trend(days: int = 14) -> dict:
    """Return daily focus scores for the last N days."""
    uid = _self_slack_uid()
    if not uid:
        return {"error": "no slack user mapped to self"}

    today = datetime.now()
    daily = []
    for i in range(days):
        d = today - timedelta(days=i)
        daily.append(_daily_focus(uid, d))
    daily.reverse()

    active_days = [d for d in daily if d["messages"] > 0]
    if not active_days:
        return {
            "period_days": days,
            "active_days": 0,
            "avg_focus_score": None,
            "avg_context_switches": 0,
            "avg_messages_per_day": 0,
            "best_day": None,
            "worst_day": None,
            "daily": daily,
            "status": "no_data",
            "message": "No Slack messages from the mapped self user in this range.",
        }

    avg_score = round(
        sum(d["focus_score"] or 0 for d in active_days) / len(active_days), 1
    )
    best = max(active_days, key=lambda d: d["focus_score"] or 0)
    worst = min(active_days, key=lambda d: d["focus_score"] or 100)
    avg_switches = round(sum(d["context_switches"] for d in active_days) / len(active_days), 1)
    avg_msgs = round(sum(d["messages"] for d in active_days) / len(active_days), 1)

    return {
        "period_days": days,
        "active_days": len(active_days),
        "avg_focus_score": avg_score,
        "avg_context_switches": avg_switches,
        "avg_messages_per_day": avg_msgs,
        "best_day": {"date": best["date"], "score": best["focus_score"]},
        "worst_day": {"date": worst["date"], "score": worst["focus_score"]},
        "daily": daily,
    }
