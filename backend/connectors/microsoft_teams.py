"""Read-only Microsoft Teams connector using Microsoft Graph."""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class MicrosoftTeamsConnector:
    name = "microsoft_teams"
    graph_base = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        token: str | None = None,
        team_id: str | None = None,
        channel_id: str | None = None,
        chat_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_TEAMS_TOKEN", "")
        self.team_id = team_id if team_id is not None else os.getenv("SUDOBRAIN_TEAMS_TEAM_ID", "")
        self.channel_id = channel_id if channel_id is not None else os.getenv("SUDOBRAIN_TEAMS_CHANNEL_ID", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("SUDOBRAIN_TEAMS_CHAT_ID", "")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.graph_base}{path}", headers=self._headers(), params=params or {}, timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_TEAMS_TOKEN not configured",
            }
        try:
            user = self._get("/me")
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "team_id": self.team_id,
                "channel_id": self.channel_id,
                "chat_id": self.chat_id,
                "user": user.get("userPrincipalName", ""),
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
        documents: list[SourceDocument] = []
        if self.team_id and self.channel_id:
            documents.extend(self._fetch_channel_messages(limit))
        if self.chat_id and len(documents) < limit:
            documents.extend(self._fetch_chat_messages(limit - len(documents)))
        if len(documents) < limit:
            documents.extend(self._fetch_events(limit - len(documents)))
        return documents[:limit]

    def _fetch_channel_messages(self, limit: int) -> list[SourceDocument]:
        payload = self._get(
            f"/teams/{self.team_id}/channels/{self.channel_id}/messages",
            {"$top": max(1, min(limit, 50))},
        )
        return [self._document_from_message(item, "channel_message") for item in payload.get("value", [])]

    def _fetch_chat_messages(self, limit: int) -> list[SourceDocument]:
        payload = self._get(f"/chats/{self.chat_id}/messages", {"$top": max(1, min(limit, 50))})
        return [self._document_from_message(item, "chat_message") for item in payload.get("value", [])]

    def _fetch_events(self, limit: int) -> list[SourceDocument]:
        try:
            payload = self._get("/me/events", {"$top": max(1, min(limit, 50)), "$orderby": "lastModifiedDateTime desc"})
        except Exception:
            return []
        return [self._document_from_event(item) for item in payload.get("value", [])]

    def _document_from_message(self, item: dict[str, Any], kind: str) -> SourceDocument:
        sender = (((item.get("from") or {}).get("user") or {}).get("displayName") or "")
        body = (item.get("body") or {}).get("content") or ""
        attachments = item.get("attachments") or []
        text = "\n".join(part for part in [
            _strip_html(body),
            f"From: {sender}" if sender else "",
            "\n".join(f"Attachment: {att.get('name') or att.get('contentUrl')}" for att in attachments),
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"{kind}:{item.get('id')}",
            title=(text.splitlines()[0][:120] if text else "Teams message"),
            text=text,
            occurred_at=item.get("lastModifiedDateTime") or item.get("createdDateTime"),
            author=sender,
            url=item.get("webUrl"),
            metadata={
                "kind": kind,
                "id": item.get("id"),
                "importance": item.get("importance"),
                "attachments": [
                    {"id": att.get("id"), "name": att.get("name"), "content_type": att.get("contentType")}
                    for att in attachments
                ],
            },
        )

    def _document_from_event(self, item: dict[str, Any]) -> SourceDocument:
        attendees = [
            ((att.get("emailAddress") or {}).get("name") or (att.get("emailAddress") or {}).get("address") or "")
            for att in item.get("attendees", [])
        ]
        text = "\n".join(part for part in [
            item.get("subject") or "Teams meeting",
            _strip_html((item.get("body") or {}).get("content") or ""),
            f"Attendees: {', '.join(att for att in attendees if att)}" if attendees else "",
            f"Online meeting: {((item.get('onlineMeeting') or {}).get('joinUrl') or '')}",
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"event:{item.get('id')}",
            title=item.get("subject") or "Teams meeting",
            text=text,
            occurred_at=item.get("lastModifiedDateTime") or ((item.get("start") or {}).get("dateTime")),
            author=((item.get("organizer") or {}).get("emailAddress") or {}).get("name"),
            url=item.get("webLink"),
            metadata={
                "kind": "meeting",
                "id": item.get("id"),
                "start": item.get("start"),
                "end": item.get("end"),
                "attendees": attendees,
                "has_attachments": bool(item.get("hasAttachments")),
            },
        )


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", without_tags).strip()


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
