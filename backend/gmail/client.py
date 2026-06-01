"""Gmail client — direct Gmail API.

Fetches emails with full body in seconds using Google API Python client.
Authenticated via OAuth2 credentials.json + token.json.
READ-ONLY: only gmail.readonly scope.
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sudobrain.gmail")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = os.getenv(
    "GMAIL_CREDENTIALS_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "credentials.json"),
)
TOKEN_FILE = os.getenv(
    "GMAIL_TOKEN_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "token.json"),
)

# Sender domains/patterns that are automated noise
DUMP_SENDERS = [
    "notifications@github.com", "noreply@github.com",
    "@linear.app", "notify@linear.app",
    "hello@news.railway.app", "@railway.app",
    "@sprinto.com",
    "@digitalocean.com", "@aws.amazon.com", "@atlassian.com",
    "no-reply@", "noreply@", "no_reply@",
    "notifications@", "notify@",
    "donotreply@", "do-not-reply@",
    "mailer@", "bounce@", "postmaster@",
    "@list.", "newsletter@", "marketing@",
    "updates@", "digest@",
    "calendar-notification@google.com",
]

# Subject patterns that indicate automated/system emails
DUMP_SUBJECTS = [
    "pr run failed", "pr run passed", "workflow run", "pull request",
    "opened a pull request", "merged pull request", "closed pull request",
    "reviewed your pull request", "approved pull request",
    "requested your review", "pushed to", "new commit",
    "compare and pull request", "deploy", "deployment",
    "commit to", "issue #", "issue opened", "issue closed",
    "build failed", "build passed", "build succeeded", "pipeline failed",
    "ci failed", "ci passed", "test failed", "test passed",
    "unread notification", "notifications on",
    "your pending work for compliance",
    "signed in to your account", "new sign-in",
    "verify your email", "confirm your email",
    "password reset", "reset your password",
    "2-step verification", "two-factor",
    "security alert", "unusual activity",
    "invoice", "receipt", "payment confirmed",
    "canceled event", "has been canceled",
    "unsubscribe", "view in browser", "manage preferences",
]

# Attachment types worth extracting or tracking as local source evidence.
USEFUL_ATTACHMENT_TYPES = {".pdf", ".doc", ".docx", ".txt", ".md", ".csv"}
IMAGE_ATTACHMENT_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
SKIP_ATTACHMENT_TYPES = {".ics", ".ico", ".zip", ".exe"}


def _get_service():
    """Get authenticated Gmail API service."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "Gmail token not found or invalid. Run the authorization flow first."
            )

    return build("gmail", "v1", credentials=creds)


def is_available() -> bool:
    """Check if Gmail API credentials are configured."""
    try:
        _get_service()
        return True
    except Exception:
        return os.path.exists(TOKEN_FILE)


def is_dump_email(email: dict) -> bool:
    """Return True if email is automated noise, not a human email."""
    from_field = (email.get("from") or "").lower()
    subject = (email.get("subject") or "").lower()

    for pattern in DUMP_SENDERS:
        if pattern in from_field:
            return True

    for pattern in DUMP_SUBJECTS:
        if pattern in subject:
            return True

    return False


def get_profile() -> dict:
    """Get authenticated Gmail user profile."""
    try:
        service = _get_service()
        profile = service.users().getProfile(userId="me").execute()
        return {
            "email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal"),
            "threads_total": profile.get("threadsTotal"),
        }
    except Exception as e:
        logger.error("Gmail get_profile failed: %s", e)
        return {}


def _decode_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    # Multipart — recurse into parts
    if "parts" in payload:
        texts = []
        for part in payload["parts"]:
            text = _decode_body(part)
            if text:
                texts.append(text)
        return "\n".join(texts)

    return ""


def _extract_header(headers: list, name: str) -> str:
    """Extract a header value by name."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _get_attachments(payload: dict) -> list[dict]:
    """Extract attachment metadata from message payload."""
    attachments = []

    def _process_part(part):
        filename = part.get("filename", "")
        if filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in SKIP_ATTACHMENT_TYPES:
                size_bytes = part.get("body", {}).get("size", 0)
                attachments.append({
                    "name": filename,
                    "type": ext.lstrip("."),
                    "size_kb": round(size_bytes / 1024, 1),
                    "attachment_id": part.get("body", {}).get("attachmentId"),
                })
        for sub_part in part.get("parts", []):
            _process_part(sub_part)

    _process_part(payload)
    return attachments


def fetch_message(service, message_id: str) -> dict:
    """Fetch a single message with full body — fast direct API call."""
    try:
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        body = _decode_body(msg.get("payload", {}))
        attachments = _get_attachments(msg.get("payload", {}))

        # Add attachment info to body for extraction context
        if attachments:
            attach_info = "\n\n[Attachments: " + ", ".join(
                f"{a['name']} ({a['type']}, {a['size_kb']}KB)"
                for a in attachments
            ) + "]"
            body = body + attach_info

        from_field = _extract_header(headers, "From")
        to_field = _extract_header(headers, "To")
        date_field = _extract_header(headers, "Date")

        return {
            "id": message_id,
            "thread_id": msg.get("threadId"),
            "subject": _extract_header(headers, "Subject"),
            "from": from_field,
            "to": [to_field] if to_field else [],
            "date": date_field,
            "snippet": msg.get("snippet", ""),
            "body": body.strip(),
            "labels": msg.get("labelIds", []),
            "attachments": attachments,
        }
    except Exception as e:
        logger.warning("Failed to fetch message %s: %s", message_id, e)
        return {}


def search_and_fetch(query: str, max_results: int = 50) -> list[dict]:
    """Search Gmail and fetch full message content for each result.

    This uses direct API calls and applies local filters before storage.
    Returns emails with full body text ready for knowledge extraction.
    """
    try:
        service = _get_service()

        # Search for matching messages
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            logger.info("Gmail search returned 0 results for: %s", query)
            return []

        logger.info("Gmail: fetching %d messages...", len(messages))

        # Fetch full content for each message (fast direct API calls)
        from backend.gmail.attachments import process_message_attachments, extract_text, download_attachment, TEXT_EXTRACTABLE
        emails = []
        for msg_ref in messages:
            msg = fetch_message(service, msg_ref["id"])
            if msg and msg.get("body"):
                # Download + extract text from useful attachments, inline into body
                if msg.get("attachments"):
                    try:
                        stored = process_message_attachments(
                            service, msg["id"], msg["attachments"]
                        )
                        if stored:
                            # Inline extracted text so knowledge extraction sees it
                            from backend.storage.database import get_connection
                            conn = get_connection()
                            try:
                                rows = conn.execute(
                                    "SELECT filename, file_type, extracted_text FROM gmail_attachments WHERE message_id = ? AND char_count > 0",
                                    (msg["id"],),
                                ).fetchall()
                            finally:
                                conn.close()
                            extras = []
                            for r in rows:
                                extras.append(
                                    f"\n\n--- Attachment: {r['filename']} ({r['file_type']}) ---\n{r['extracted_text'][:8000]}"
                                )
                            if extras:
                                msg["body"] = msg.get("body", "") + "".join(extras)
                    except Exception as e:
                        logger.debug("attachment processing skipped for %s: %s",
                                     msg.get("id"), e)
                emails.append(msg)

        logger.info("Gmail: fetched %d messages with body content", len(emails))
        return emails

    except Exception as e:
        logger.error("Gmail search_and_fetch failed: %s", e)
        return []


def get_smart_emails(days: int = 30, max_results: int = 50) -> list[dict]:
    """Fetch human-to-human emails only — filters out all automated noise.

    Uses direct Gmail API. Returns emails ready for knowledge extraction.
    """
    query = (
        f"in:inbox newer_than:{days}d "
        f"-category:promotions -category:social "
        f"-category:updates -category:forums "
        f"-from:noreply -from:no-reply -from:notifications"
    )

    emails = search_and_fetch(query, max_results=max_results * 2)  # fetch extra to account for filtering

    # Apply smart filter
    filtered = [e for e in emails if not is_dump_email(e)]

    logger.info(
        "Gmail smart filter: %d/%d emails kept after filtering",
        len(filtered), len(emails)
    )

    return filtered[:max_results]


def search_emails(q: str, max_results: int = 20) -> list[dict]:
    """Public API wrapper used by /gmail/search."""
    return search_and_fetch(q, max_results=max_results)


def get_action_emails(max_results: int = 20) -> list[dict]:
    """Return unread, human-looking emails that likely need attention."""
    query = (
        "in:inbox is:unread "
        "-category:promotions -category:social "
        "-category:updates -category:forums "
        "-from:noreply -from:no-reply -from:notifications"
    )
    emails = search_and_fetch(query, max_results=max_results * 2)
    return [e for e in emails if not is_dump_email(e)][:max_results]


def get_attachment_text(service, message_id: str, attachment_id: str) -> str:
    """Download and extract text from a specific attachment."""
    try:
        attachment = service.users().messages().attachments().get(
            userId="me",
            messageId=message_id,
            id=attachment_id,
        ).execute()

        data = base64.urlsafe_b64decode(attachment["data"] + "==")
        return data.decode("utf-8", errors="replace")[:5000]
    except Exception as e:
        logger.warning("Failed to fetch attachment: %s", e)
        return ""
