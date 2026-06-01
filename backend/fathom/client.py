"""Fathom API client — list meetings, download MP3 via HLS, extract speaker timestamps."""

import os
import subprocess
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.fathom.ai/external/v1"
DOWNLOAD_DIR = Path(os.getenv("SUDOBRAIN_DATA_DIR", str(Path.home() / ".sudobrain"))) / "fathom" / "recordings"


def _headers() -> dict:
    token = os.getenv("FATHOM_API_TOKEN")
    if not token:
        raise ValueError("FATHOM_API_TOKEN not set in .env")
    return {"X-Api-Key": token}


def is_configured() -> bool:
    """Check if Fathom API token is configured."""
    return bool(os.getenv("FATHOM_API_TOKEN"))


# --- Fathom API ---


def list_meetings(
    limit: int = 25,
    include_transcript: bool = False,
    include_summary: bool = False,
    include_action_items: bool = False,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
) -> dict:
    """List meetings from Fathom API with optional filters."""
    params = {"limit": limit}
    if include_transcript:
        params["include_transcript"] = "true"
    if include_summary:
        params["include_summary"] = "true"
    if include_action_items:
        params["include_action_items"] = "true"
    if created_after:
        params["created_after"] = created_after
    if created_before:
        params["created_before"] = created_before

    resp = requests.get(f"{BASE_URL}/meetings", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_transcript(recording_id: str) -> dict:
    """Get transcript for a recording from Fathom API.

    Returns speaker names, emails, text, and timestamps.
    Used for speaker identification — NOT for the text content (Sarvam handles that).
    """
    resp = requests.get(
        f"{BASE_URL}/recordings/{recording_id}/transcript",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_summary(recording_id: str) -> dict:
    """Get AI summary for a recording from Fathom API."""
    resp = requests.get(
        f"{BASE_URL}/recordings/{recording_id}/summary",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# --- Speaker timestamps extraction ---


def _timestamp_to_seconds(ts: str) -> float:
    """Convert HH:MM:SS or MM:SS timestamp to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def extract_speaker_segments(recording_id: str) -> list[dict]:
    """Fetch Fathom transcript and extract speaker identification + timestamps.

    Returns a list of segments:
    [
        {
            "speaker_name": "Speaker 1",
            "speaker_email": "speaker@example.com",
            "start_seconds": 0.0,
            "end_seconds": 45.2,
        },
        ...
    ]
    """
    try:
        data = get_transcript(recording_id)
    except Exception as e:
        print(f"[Fathom] Could not fetch transcript for speaker data: {e}")
        return []

    segments = []
    entries = data.get("transcript", []) if isinstance(data, dict) else data

    for entry in entries:
        speaker = entry.get("speaker", {})
        speaker_name = speaker.get("display_name", "Unknown")
        speaker_email = speaker.get("matched_calendar_invitee_email", "") or ""
        timestamp = entry.get("timestamp", "")

        start_sec = _timestamp_to_seconds(timestamp) if timestamp else 0.0

        segments.append({
            "speaker_name": speaker_name,
            "speaker_email": speaker_email,
            "start_seconds": start_sec,
            "end_seconds": start_sec,
        })

    # Infer end times from next segment's start
    for i in range(len(segments) - 1):
        if segments[i]["end_seconds"] <= segments[i]["start_seconds"]:
            segments[i]["end_seconds"] = segments[i + 1]["start_seconds"]

    print(f"[Fathom] Extracted {len(segments)} speaker segments")

    speakers = {}
    for seg in segments:
        name = seg["speaker_name"]
        if name not in speakers:
            speakers[name] = seg.get("speaker_email", "")
    print(f"[Fathom] Speakers found: {', '.join(speakers.keys())}")

    return segments


# --- MP3 download via ffmpeg + HLS ---


def _extract_share_token(share_url: str) -> str:
    """Extract the share token from a Fathom share URL."""
    url_path = share_url.split("?")[0].rstrip("/")
    token = url_path.split("/")[-1]
    if not token:
        raise ValueError(f"Could not extract share token from: {share_url}")
    return token


def download_audio(share_url: str, recording_id: str, output_dir: Optional[str] = None) -> str:
    """Download MP3 from Fathom using ffmpeg + HLS manifest.

    Returns path to the downloaded MP3 file.
    """
    out_dir = Path(output_dir) if output_dir else DOWNLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{recording_id}.mp3"

    if output_path.exists():
        print(f"[Fathom] Audio already downloaded: {output_path}")
        return str(output_path)

    token = _extract_share_token(share_url)
    hls_url = f"https://fathom.video/share/{token}/video.m3u8"

    print(f"[Fathom] Downloading audio via yt-dlp (parallel HLS fragments)...")

    output_template = str(out_dir / f"{recording_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--force-generic-extractor",
        "--concurrent-fragments", "16",
        "--no-warnings",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "128K",
        "-o", output_template,
        hls_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

    if result.returncode != 0 and not output_path.exists():
        raise RuntimeError(
            f"yt-dlp failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
            "Make sure yt-dlp is installed: brew install yt-dlp"
        )

    if not output_path.exists():
        raise FileNotFoundError(f"yt-dlp completed but MP3 not found at {output_path}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[Fathom] Downloaded: {output_path} ({size_mb:.1f} MB)")
    return str(output_path)


def download_audio_from_recording(recording_id: str, output_dir: Optional[str] = None) -> str:
    """Look up share_url from API by recording_id, then download."""
    meetings = list_meetings(limit=100)
    recordings = meetings.get("items", meetings.get("recordings", []))

    share_url = None
    for meeting in recordings:
        rid = str(meeting.get("recording_id", ""))
        if rid == str(recording_id):
            share_url = meeting.get("share_url") or meeting.get("url")
            break

    if not share_url:
        raise ValueError(f"Recording {recording_id} not found or has no share URL")

    return download_audio(share_url, str(recording_id), output_dir)


def fetch_meeting_metadata(recording_id: str, share_url: str) -> dict:
    """Fetch meeting metadata from Fathom API — title, times, invitees."""
    try:
        meetings = list_meetings(limit=100)
        for m in meetings.get("items", []):
            rid = str(m.get("recording_id", ""))
            surl = m.get("share_url", "")
            if rid == str(recording_id) or share_url in surl or surl in share_url:
                return {
                    "title": m.get("title", ""),
                    "meeting_title": m.get("meeting_title", ""),
                    "recording_id": rid,
                    "url": m.get("url", ""),
                    "share_url": m.get("share_url", ""),
                    "recording_start_time": m.get("recording_start_time", ""),
                    "recording_end_time": m.get("recording_end_time", ""),
                    "scheduled_start_time": m.get("scheduled_start_time", ""),
                    "scheduled_end_time": m.get("scheduled_end_time", ""),
                    "transcript_language": m.get("transcript_language", ""),
                    "recorded_by": m.get("recorded_by", {}),
                    "calendar_invitees": m.get("calendar_invitees", []),
                }
    except Exception as e:
        print(f"[Fathom] Warning: Could not fetch meeting metadata: {e}")

    return {"recording_id": str(recording_id), "title": "Unknown Meeting"}
