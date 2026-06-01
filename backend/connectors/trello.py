"""Read-only Trello connector."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class TrelloConnector:
    name = "trello"
    api_base = "https://api.trello.com/1"

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        board_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("SUDOBRAIN_TRELLO_API_KEY", "")
        self.token = token if token is not None else os.getenv("SUDOBRAIN_TRELLO_TOKEN", "")
        self.board_id = board_id if board_id is not None else os.getenv("SUDOBRAIN_TRELLO_BOARD_ID", "")
        self.session = session or requests.Session()

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {"key": self.api_key, "token": self.token}
        params.update(extra or {})
        return params

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(f"{self.api_base}{path}", params=self._params(params), timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        configured = bool(self.api_key and self.token)
        if not configured:
            return {
                "name": self.name,
                "ok": False,
                "api_key_configured": bool(self.api_key),
                "token_configured": bool(self.token),
                "detail": "SUDOBRAIN_TRELLO_API_KEY and SUDOBRAIN_TRELLO_TOKEN are required",
            }
        try:
            member = self._get("/members/me", {"fields": "username,fullName"})
            return {
                "name": self.name,
                "ok": True,
                "api_key_configured": True,
                "token_configured": True,
                "board_id": self.board_id,
                "member": member.get("username", ""),
                "detail": "reachable",
            }
        except Exception as exc:
            return {
                "name": self.name,
                "ok": False,
                "api_key_configured": True,
                "token_configured": True,
                "detail": str(exc)[:300],
            }

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        limit = max(1, min(limit, 100))
        board_ids = [self.board_id] if self.board_id else self._member_board_ids(limit=10)
        documents: list[SourceDocument] = []
        for board_id in board_ids:
            documents.extend(self._fetch_board_cards(board_id, limit=max(1, limit - len(documents))))
            if len(documents) >= limit:
                break
        return documents[:limit]

    def _member_board_ids(self, limit: int) -> list[str]:
        boards = self._get("/members/me/boards", {"fields": "id,name", "filter": "open"})
        return [board.get("id") for board in boards[:limit] if board.get("id")]

    def _fetch_board_cards(self, board_id: str, limit: int) -> list[SourceDocument]:
        cards = self._get(
            f"/boards/{board_id}/cards",
            {
                "limit": limit,
                "fields": "name,desc,due,dueComplete,dateLastActivity,shortUrl,idList,idBoard,labels,idMembers,closed",
                "actions": "commentCard",
                "actions_limit": 10,
                "members": "true",
                "member_fields": "fullName,username",
                "list": "true",
            },
        )
        return [self._document_from_card(card) for card in cards[:limit]]

    def _document_from_card(self, card: dict[str, Any]) -> SourceDocument:
        title = card.get("name") or "Trello card"
        members = [
            member.get("fullName") or member.get("username") or ""
            for member in card.get("members", [])
            if member.get("fullName") or member.get("username")
        ]
        labels = [label.get("name") for label in card.get("labels", []) if label.get("name")]
        comments = []
        for action in card.get("actions", []):
            data = action.get("data") or {}
            text = (data.get("text") or "").strip()
            if text:
                actor = ((action.get("memberCreator") or {}).get("fullName") or "unknown")
                comments.append(f"Comment by {actor}: {text}")
        text = "\n".join(part for part in [
            title,
            card.get("desc") or "",
            f"Due: {card.get('due')}" if card.get("due") else "",
            f"Done: {bool(card.get('dueComplete'))}",
            f"Members: {', '.join(members)}" if members else "",
            f"Labels: {', '.join(labels)}" if labels else "",
            "\n".join(comments),
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"card:{card.get('id')}",
            title=title,
            text=text,
            occurred_at=card.get("dateLastActivity"),
            author=", ".join(members),
            url=card.get("shortUrl"),
            metadata={
                "kind": "card",
                "id": card.get("id"),
                "board_id": card.get("idBoard"),
                "list_id": card.get("idList"),
                "closed": bool(card.get("closed")),
                "due": card.get("due"),
                "due_complete": bool(card.get("dueComplete")),
                "members": members,
                "labels": labels,
            },
        )


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
