"""Recurring meeting rot.

Detects standing meetings (via Google Calendar) with declining output over time.
For each recurring event pattern (same title + attendee set), compute:
  - total_instances
  - recent_instances_with_output (fathom processed + extracted)
  - output_trend (slope across instances)
  - rot_score (higher = more rot)

Without Fathom data we return the structural signal only: recurring events whose
attendee_count is high relative to their age/cadence.
"""

from datetime import datetime, timedelta, timezone


def compute_meeting_rot() -> dict:
    try:
        from backend.calendar import direct_client as cal
    except Exception:
        return {"error": "calendar client unavailable"}

    try:
        # Look at past 60 days + next 14 days for recurring patterns
        events = cal.get_recent_window(days_back=60, days_forward=14)
    except Exception as e:
        return {"error": f"get_recent_window failed: {e}"}

    if not events:
        return {"recurring_count": 0, "meetings": []}

    # Group by title (recurring events share a title)
    groups: dict[str, list[dict]] = {}
    for e in events:
        t = (e.get("title") or "").strip()
        if not t:
            continue
        groups.setdefault(t, []).append(e)

    # Only recurring patterns (>=3 instances in 60 days)
    recurring = {k: v for k, v in groups.items() if len(v) >= 3}

    results = []
    for title, instances in recurring.items():
        count = len(instances)
        # person-minutes total
        total_pm = 0
        for inst in instances:
            dur = 30  # default
            try:
                start = datetime.fromisoformat(inst["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(inst["end"].replace("Z", "+00:00"))
                dur = max(1, int((end - start).total_seconds() / 60))
            except Exception:
                pass
            att = len(inst.get("attendees", []) or [])
            total_pm += dur * max(1, att)

        results.append({
            "title": title,
            "instances": count,
            "total_person_minutes": total_pm,
            "avg_attendees": round(
                sum(len(i.get("attendees") or []) for i in instances) / count, 1
            ),
            # Without output tracking we can't score rot; mark as unknown
            "output_score": None,
            "rot_warning": total_pm > 500 and count > 4,
        })

    results.sort(key=lambda m: -m["total_person_minutes"])
    return {
        "recurring_count": len(results),
        "meetings": results,
    }
