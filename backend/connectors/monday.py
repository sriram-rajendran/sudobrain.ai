"""Read-only Monday.com connector."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class MondayConnector:
    name = "monday"
    api_url = "https://api.monday.com/v2"

    def __init__(
        self,
        token: str | None = None,
        board_ids: str | list[str] | None = None,
        session: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_MONDAY_TOKEN", "")
        raw_board_ids = board_ids if board_ids is not None else os.getenv("SUDOBRAIN_MONDAY_BOARD_IDS", "")
        if isinstance(raw_board_ids, str):
            self.board_ids = [item.strip() for item in raw_board_ids.split(",") if item.strip()]
        else:
            self.board_ids = [str(item).strip() for item in raw_board_ids if str(item).strip()]
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "SudoBrain"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.post(
            self.api_url,
            headers=self._headers(),
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(str(payload["errors"])[:500])
        return payload

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_MONDAY_TOKEN not configured",
            }
        try:
            payload = self._graphql("query { me { id name } }")
            user = ((payload.get("data") or {}).get("me") or {})
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "board_ids": self.board_ids,
                "user_id": user.get("id", ""),
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
        if self.board_ids:
            query = """
            query SudoBrainMonday($ids: [ID!], $limit: Int!) {
              boards(ids: $ids) {
                id
                name
                items_page(limit: $limit) {
                  items {
                    id
                    name
                    updated_at
                    url
                    column_values { id text type }
                  }
                }
              }
            }
            """
            variables = {"ids": self.board_ids, "limit": limit}
        else:
            query = """
            query SudoBrainMonday($limit: Int!) {
              boards(limit: 10) {
                id
                name
                items_page(limit: $limit) {
                  items {
                    id
                    name
                    updated_at
                    url
                    column_values { id text type }
                  }
                }
              }
            }
            """
            variables = {"limit": limit}
        payload = self._graphql(query, variables)
        boards = ((payload.get("data") or {}).get("boards") or [])
        documents: list[SourceDocument] = []
        for board in boards:
            items = ((board.get("items_page") or {}).get("items") or [])
            for item in items:
                documents.append(self._document_from_item(board, item))
                if len(documents) >= limit:
                    return documents
        return documents

    def _document_from_item(self, board: dict[str, Any], item: dict[str, Any]) -> SourceDocument:
        title = item.get("name") or "Monday item"
        columns = item.get("column_values") or []
        column_lines = [
            f"{column.get('id')}: {column.get('text')}"
            for column in columns
            if column.get("text")
        ]
        text = "\n".join(part for part in [
            title,
            f"Board: {board.get('name', '')}" if board.get("name") else "",
            "\n".join(column_lines),
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"item:{item.get('id')}",
            title=title,
            text=text,
            occurred_at=item.get("updated_at"),
            author=None,
            url=item.get("url"),
            metadata={
                "kind": "item",
                "id": item.get("id"),
                "board_id": board.get("id"),
                "board_name": board.get("name"),
                "columns": [
                    {"id": column.get("id"), "type": column.get("type"), "text": column.get("text")}
                    for column in columns
                ],
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
