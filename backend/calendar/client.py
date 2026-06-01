"""Google Calendar client — read-only direct API facade.

Fetches today's events, upcoming meetings, and provides pre-meeting prep context.
"""

import logging
from datetime import datetime

logger = logging.getLogger("sudobrain.calendar")


def is_available() -> bool:
    from backend.calendar.direct_client import is_available as direct_available
    return direct_available()


def get_todays_events() -> list[dict]:
    """Fetch all events for today through the direct Google Calendar API."""
    from backend.calendar.direct_client import get_todays_events as direct_today
    return direct_today()


def get_upcoming_events(days: int = 3) -> list[dict]:
    """Fetch events for the next N days through the direct Google Calendar API."""
    from backend.calendar.direct_client import get_upcoming_events as direct_upcoming
    return direct_upcoming(days=days)


def get_next_meeting() -> dict | None:
    """Get the next upcoming meeting from now."""
    events = get_todays_events()
    now = datetime.now()
    upcoming = []
    for e in events:
        try:
            start_str = e.get("start", "")
            if "T" in start_str:
                start = datetime.fromisoformat(start_str.replace("Z", ""))
                if start > now:
                    upcoming.append((start, e))
        except (ValueError, TypeError):
            pass

    if not upcoming:
        return None

    upcoming.sort(key=lambda x: x[0])
    return upcoming[0][1]


def get_meeting_attendees(event: dict) -> list[str]:
    """Extract attendee names from a calendar event."""
    attendees = event.get("attendees", [])
    names = []
    for a in attendees:
        if "<" in a:
            name = a.split("<")[0].strip().strip('"')
            if name:
                names.append(name)
        elif "@" in a:
            names.append(a.split("@")[0])
        else:
            names.append(a)
    return names


def get_calendar_briefing_context() -> str:
    """Generate calendar context for the morning briefing."""
    try:
        events = get_todays_events()
        if not events:
            return "No calendar events today."

        lines = [f"TODAY'S MEETINGS ({len(events)} total):"]
        for e in events:
            title = e.get("title", "Untitled")
            start = e.get("start", "")[:16].replace("T", " ")
            end = e.get("end", "")[:16].replace("T", " ")
            attendees = get_meeting_attendees(e)
            attendee_str = ", ".join(attendees[:4]) if attendees else "no attendees"
            lines.append(f"  - {start}: {title} (with {attendee_str})")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("Calendar briefing context failed: %s", e)
        return ""


def get_pre_meeting_context(event: dict) -> dict:
    """Get prep context for an upcoming meeting — pulls from SudoBrain knowledge."""
    attendees = get_meeting_attendees(event)
    title = event.get("title", "Meeting")

    try:
        from backend.intelligence.meeting_prep import prepare_for_meeting
        prep = prepare_for_meeting(attendees, title)
        return {
            "event": event,
            "attendees": attendees,
            "prep": prep,
        }
    except Exception as e:
        logger.warning("Pre-meeting context failed: %s", e)
        return {"event": event, "attendees": attendees, "prep": {}}
