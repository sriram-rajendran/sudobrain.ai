"""Read-only Notion connector."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class NotionConnector:
    name = "notion"
    api_base = "https://api.notion.com/v1"
    notion_version = "2022-06-28"

    def __init__(self, token: str | None = None, session: Any | None = None) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_NOTION_TOKEN", "")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
            "User-Agent": "SudoBrain",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.api_base}{path}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _get(self, path: str) -> dict[str, Any]:
        response = self.session.get(f"{self.api_base}{path}", headers=self._headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_NOTION_TOKEN not configured",
            }
        try:
            user = self._get("/" + "users" + "/me")
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "workspace_name": (user.get("bot") or {}).get("workspace_name", ""),
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
        payload = {
            "page_size": limit,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        results = self._post("/search", payload).get("results", [])
        return [self._document_from_result(item) for item in results[:limit]]

    def _document_from_result(self, item: dict[str, Any]) -> SourceDocument:
        kind = item.get("object", "notion_object")
        title = _title_from_item(item)
        external_id = str(item.get("id") or title)
        url = item.get("url")
        text = "\n".join(part for part in [
            title,
            f"Type: {kind}",
            _plain_property_summary(item.get("properties") or {}),
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"{kind}:{external_id}",
            title=title or "Notion item",
            text=text,
            occurred_at=item.get("last_edited_time") or item.get("created_time"),
            author=((item.get("last_edited_by") or {}).get("id") or (item.get("created_by") or {}).get("id")),
            url=url,
            metadata={
                "kind": kind,
                "id": external_id,
                "created_time": item.get("created_time"),
                "last_edited_time": item.get("last_edited_time"),
                "archived": item.get("archived", False),
            },
        )


def _title_from_item(item: dict[str, Any]) -> str:
    properties = item.get("properties") or {}
    for prop in properties.values():
        if prop.get("type") == "title":
            text = "".join(part.get("plain_text", "") for part in prop.get("title", []))
            if text:
                return text
    if item.get("object") == "database":
        return "".join(part.get("plain_text", "") for part in item.get("title", [])) or "Notion database"
    return "Notion page"


def _plain_property_summary(properties: dict[str, Any]) -> str:
    lines: list[str] = []
    for name, prop in list(properties.items())[:20]:
        prop_type = prop.get("type")
        value = prop.get(prop_type) if prop_type else None
        if prop_type == "title":
            value = "".join(part.get("plain_text", "") for part in value or [])
        elif prop_type == "rich_text":
            value = "".join(part.get("plain_text", "") for part in value or [])
        elif prop_type == "select":
            value = (value or {}).get("name")
        elif prop_type == "multi_select":
            value = ", ".join(item.get("name", "") for item in value or [])
        elif prop_type in {"date", "people", "files", "relation", "rollup", "formula"}:
            value = prop_type
        if value not in (None, "", []):
            lines.append(f"{name}: {value}")
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
