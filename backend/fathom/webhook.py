"""Fathom webhook signature verification and event parsing."""

import base64
import hashlib
import hmac
import os
import time

from dotenv import load_dotenv

load_dotenv()

TIMESTAMP_TOLERANCE_SECONDS = 300


def _get_secret() -> bytes:
    """Get webhook secret, stripping the whsec_ prefix for HMAC signing."""
    secret = os.getenv("FATHOM_WEBHOOK_SECRET", "")
    if not secret:
        raise ValueError("FATHOM_WEBHOOK_SECRET not set in .env")
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    return base64.b64decode(secret)


def verify_webhook(
    payload: bytes,
    webhook_id: str,
    webhook_timestamp: str,
    webhook_signature: str,
) -> bool:
    """Verify a Fathom webhook signature."""
    try:
        ts = int(webhook_timestamp)
    except ValueError:
        return False

    if abs(time.time() - ts) > TIMESTAMP_TOLERANCE_SECONDS:
        return False

    signed_content = f"{webhook_id}.{webhook_timestamp}.{payload.decode('utf-8')}"
    secret = _get_secret()

    expected = base64.b64encode(
        hmac.new(secret, signed_content.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    signatures = webhook_signature.split(" ")
    for sig in signatures:
        parts = sig.split(",", 1)
        sig_value = parts[1] if len(parts) == 2 else parts[0]
        if hmac.compare_digest(expected, sig_value):
            return True

    return False


def parse_webhook_event(payload: dict) -> dict:
    """Parse a Fathom webhook payload and extract key fields."""
    return {
        "recording_id": str(payload.get("recording_id", "")),
        "event_type": payload.get("type", "meeting_content_ready"),
        "title": payload.get("title", "Untitled Meeting"),
        "share_url": payload.get("share_url", ""),
        "url": payload.get("url", ""),
        "created_at": payload.get("created_at", ""),
        "recording_start_time": payload.get("recording_start_time", ""),
        "recording_end_time": payload.get("recording_end_time", ""),
        "has_transcript": "transcript" in payload and payload["transcript"] is not None,
        "has_summary": "default_summary" in payload and payload["default_summary"] is not None,
        "has_action_items": "action_items" in payload and payload["action_items"] is not None,
    }
