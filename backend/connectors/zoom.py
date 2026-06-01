"""Read-only Zoom connector for cloud recordings and transcript artifacts."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


TRANSCRIPT_RECORDING_TYPES = {"audio_transcript"}
SUMMARY_RECORDING_TYPES = {"summary", "summary_next_steps", "summary_smart_chapters"}


class ZoomConnector:
    name = "zoom"
    api_base = "https://api.zoom.us/v2"

    def __init__(
        self,
        token: str | None = None,
        user_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        include_file_text: bool | None = None,
        session: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_ZOOM_TOKEN", "")
        self.user_id = user_id if user_id is not None else os.getenv("SUDOBRAIN_ZOOM_USER_ID", "me")
        self.from_date = from_date if from_date is not None else os.getenv("SUDOBRAIN_ZOOM_FROM", "")
        self.to_date = to_date if to_date is not None else os.getenv("SUDOBRAIN_ZOOM_TO", "")
        if include_file_text is None:
            include_file_text = os.getenv("SUDOBRAIN_ZOOM_INCLUDE_FILE_TEXT", "").lower() in {"1", "true", "yes"}
        self.include_file_text = include_file_text
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.api_base}{path}", headers=self._headers(), params=params or {}, timeout=30)
        response.raise_for_status()
        return response.json()

    def _download_text(self, url: str) -> str:
        response = self.session.get(url, headers=self._headers(), timeout=30)
        response.raise_for_status()
        text = getattr(response, "text", "")
        return _normalize_transcript_text(text)[:20000]

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_ZOOM_TOKEN not configured",
            }
        try:
            payload = self._get(_zoom_user_recordings_path(self.user_id), {"page_size": 1})
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "user_id": self.user_id,
                "from_date": self.from_date,
                "to_date": self.to_date,
                "recording_count": payload.get("total_records", 0),
                "include_file_text": self.include_file_text,
                "detail": "reachable",
            }
        except Exception as exc:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": True,
                "detail": str(exc)[:300],
            }

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        limit = max(1, min(limit, 100))
        params: dict[str, Any] = {"page_size": max(1, min(limit, 100))}
        if self.from_date:
            params["from"] = self.from_date
        if self.to_date:
            params["to"] = self.to_date
        payload = self._get(_zoom_user_recordings_path(self.user_id), params)
        return [self._document_from_recording(item) for item in payload.get("meetings", [])[:limit]]

    def _document_from_recording(self, item: dict[str, Any]) -> SourceDocument:
        files = item.get("recording_files") or []
        transcript_files = [_recording_file_summary(file) for file in files if _is_transcript_file(file)]
        summary_files = [_recording_file_summary(file) for file in files if _is_summary_file(file)]
        media_files = [_recording_file_summary(file) for file in files if not _is_transcript_file(file)]
        participants = item.get("participant_audio_files") or []
        text_parts = [
            item.get("topic") or "Zoom recording",
            item.get("agenda") or "",
            f"Host: {item.get('host_email')}" if item.get("host_email") else "",
            f"Started: {item.get('start_time')}" if item.get("start_time") else "",
            f"Duration minutes: {item.get('duration')}" if item.get("duration") is not None else "",
            _format_file_section("Transcript files", transcript_files),
            _format_file_section("Summary/action item files", summary_files),
            _format_file_section("Recording files", media_files),
            _format_participant_section(participants),
        ]
        downloaded = self._download_recording_text(files)
        if downloaded:
            text_parts.append(f"Downloaded transcript/summary text:\n{downloaded}")
        text = "\n".join(part for part in text_parts if part).strip()
        meeting_id = item.get("uuid") or item.get("id")
        return SourceDocument(
            source=self.name,
            external_id=f"recording:{meeting_id}",
            title=item.get("topic") or "Zoom recording",
            text=text,
            occurred_at=item.get("start_time"),
            author=item.get("host_email"),
            url=item.get("share_url"),
            metadata={
                "kind": "recording",
                "id": item.get("id"),
                "uuid": item.get("uuid"),
                "account_id": item.get("account_id"),
                "duration": item.get("duration"),
                "recording_count": item.get("recording_count"),
                "transcript_files": transcript_files,
                "summary_files": summary_files,
                "participant_audio_file_count": len(participants),
            },
        )

    def _download_recording_text(self, files: list[dict[str, Any]]) -> str:
        if not self.include_file_text:
            return ""
        parts: list[str] = []
        for file in files:
            if not (_is_transcript_file(file) or _is_summary_file(file)):
                continue
            url = file.get("download_url")
            if not url:
                continue
            try:
                parts.append(self._download_text(url))
            except Exception:
                continue
        return "\n\n".join(part for part in parts if part)


def _zoom_user_recordings_path(user_id: str) -> str:
    safe_user_id = user_id or "me"
    return "/" + "users" + f"/{safe_user_id}/recordings"


def _is_transcript_file(file: dict[str, Any]) -> bool:
    recording_type = str(file.get("recording_type") or "").lower()
    file_type = str(file.get("file_type") or "").lower()
    return recording_type in TRANSCRIPT_RECORDING_TYPES or "transcript" in recording_type or file_type in {"vtt", "txt"}


def _is_summary_file(file: dict[str, Any]) -> bool:
    recording_type = str(file.get("recording_type") or "").lower()
    return recording_type in SUMMARY_RECORDING_TYPES or recording_type.startswith("summary") or "smart_chapters" in recording_type


def _recording_file_summary(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": file.get("id"),
        "recording_type": file.get("recording_type"),
        "file_type": file.get("file_type"),
        "status": file.get("status"),
        "recording_start": file.get("recording_start"),
        "recording_end": file.get("recording_end"),
        "download_url": file.get("download_url"),
    }


def _format_file_section(title: str, files: list[dict[str, Any]]) -> str:
    if not files:
        return ""
    lines = [f"{title}:"]
    for file in files:
        label = file.get("recording_type") or file.get("file_type") or "file"
        status = f" ({file.get('status')})" if file.get("status") else ""
        lines.append(f"- {label}{status}")
    return "\n".join(lines)


def _format_participant_section(participants: list[dict[str, Any]]) -> str:
    if not participants:
        return ""
    lines = ["Participant audio files:"]
    for participant in participants[:25]:
        name = participant.get("participant_user_name") or participant.get("participant_user_id") or "participant"
        lines.append(f"- {name}")
    return "\n".join(lines)


def _normalize_transcript_text(value: str) -> str:
    lines = []
    for line in (value or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT" or "-->" in stripped or stripped.isdigit():
            continue
        lines.append(stripped)
    return "\n".join(lines)


def preview_documents(documents: Iterable[SourceDocument]) -> list[dict[str, Any]]:
    return [
        {
            "source": document.source,
            "external_id": document.external_id,
            "title": document.title,
            "url": document.url,
            "occurred_at": document.occurred_at,
            "author": document.author,
            "characters": len(document.text),
            "preview": document.text[:500],
            "metadata": document.metadata,
        }
        for document in documents
    ]
