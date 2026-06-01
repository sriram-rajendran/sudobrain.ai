"""Google Calendar — direct API.

Uses google-api-python-client + same credentials.json as Gmail.
Stores its own token at gcal_token.json so calendar scope auth is independent.
"""

import logging
import os
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sudobrain.calendar.direct")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = os.getenv(
    "GMAIL_CREDENTIALS_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "credentials.json"),
)
TOKEN_FILE = os.getenv(
    "GCAL_TOKEN_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "gcal_token.json"),
)


def _get_service():
    """Get authenticated Calendar API service."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "Calendar token not found. Run authorize_calendar() once "
                "(opens a browser) to grant calendar.readonly scope."
            )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def authorize_calendar():
    """Run OAuth flow once to grant calendar.readonly. Opens a browser."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"credentials.json not found at {CREDENTIALS_FILE}")
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"saved {TOKEN_FILE}")


def is_available() -> bool:
    try:
        _get_service()
        return True
    except Exception:
        return False


def _format_event(e: dict) -> dict:
    start = e.get("start", {})
    end = e.get("end", {})
    is_all_day = "date" in start
    return {
        "id": e.get("id"),
        "title": e.get("summary", "").strip(),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "attendees": [
            f"{a.get('displayName') or ''} <{a.get('email')}>".strip()
            for a in (e.get("attendees") or [])
            if a.get("email")
        ],
        "attendee_emails": [
            a["email"].lower() for a in (e.get("attendees") or []) if a.get("email")
        ],
        "location": e.get("location", ""),
        "description": e.get("description", "")[:1000] if e.get("description") else "",
        "is_all_day": is_all_day,
        "html_link": e.get("htmlLink"),
        "recurring_event_id": e.get("recurringEventId"),
        "status": e.get("status"),
    }


def list_events(start: datetime, end: datetime, max_results: int = 250) -> list[dict]:
    """Fetch all events between start and end (inclusive)."""
    service = _get_service()
    results: list[dict] = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=min(max_results, 250),
            pageToken=page_token,
        ).execute()
        for e in resp.get("items", []):
            if e.get("status") == "cancelled":
                continue
            results.append(_format_event(e))
        page_token = resp.get("nextPageToken")
        if not page_token or len(results) >= max_results:
            break
    return results


def get_todays_events() -> list[dict]:
    today = date.today()
    start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    end = datetime.combine(today, time.max, tzinfo=timezone.utc)
    return list_events(start, end)


def get_upcoming_events(days: int = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    return list_events(now, end)


def get_past_events(days: int = 30) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    return list_events(start, now)


def get_recent_window(days_back: int = 30, days_forward: int = 14) -> list[dict]:
    now = datetime.now(timezone.utc)
    return list_events(now - timedelta(days=days_back), now + timedelta(days=days_forward))


def get_next_meeting() -> Optional[dict]:
    events = get_upcoming_events(days=2)
    for e in events:
        if e["is_all_day"]:
            continue
        return e
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        authorize_calendar()
    else:
        print("today:", len(get_todays_events()))
        print("upcoming 7d:", len(get_upcoming_events(7)))
