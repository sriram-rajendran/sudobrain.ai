"""Read-only Confluence connector."""

from __future__ import annotations

import base64
import os
import re
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class ConfluenceConnector:
    name = "confluence"

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
        bearer_token: str | None = None,
        space_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("SUDOBRAIN_CONFLUENCE_BASE_URL", "")).rstrip("/")
        self.email = email if email is not None else os.getenv("SUDOBRAIN_CONFLUENCE_EMAIL", "")
        self.token = token if token is not None else os.getenv("SUDOBRAIN_CONFLUENCE_TOKEN", "")
        self.bearer_token = bearer_token if bearer_token is not None else os.getenv("SUDOBRAIN_CONFLUENCE_BEARER_TOKEN", "")
        self.space_id = space_id if space_id is not None else os.getenv("SUDOBRAIN_CONFLUENCE_SPACE_ID", "")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.email and self.token:
            raw = f"{self.email}:{self.token}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        return headers

    def _url(self, path: str) -> str:
        api_root = self.base_url
        if not api_root.endswith("/wiki"):
            api_root += "/wiki"
        return f"{api_root}{path}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(self._url(path), headers=self._headers(), params=params or {}, timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        configured = bool(self.base_url and (self.bearer_token or (self.email and self.token)))
        if not configured:
            return {
                "name": self.name,
                "ok": False,
                "base_url_configured": bool(self.base_url),
                "token_configured": bool(self.bearer_token or self.token),
                "detail": "Confluence base URL and read-only token are required",
            }
        try:
            spaces = self._get("/api/v2/spaces", {"limit": 1})
            return {
                "name": self.name,
                "ok": True,
                "base_url_configured": True,
                "token_configured": True,
                "spaces_seen": len(spaces.get("results", [])),
                "detail": "reachable",
            }
        except Exception as exc:
            return {
                "name": self.name,
                "ok": False,
                "base_url_configured": True,
                "token_configured": True,
                "detail": str(exc)[:300],
            }

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        limit = max(1, min(limit, 100))
        params: dict[str, Any] = {"limit": limit, "body-format": "storage", "sort": "-modified-date"}
        if self.space_id:
            params["space-id"] = self.space_id
        payload = self._get("/api/v2/pages", params)
        pages = payload.get("results", [])
        return [self._document_from_page(page) for page in pages[:limit]]

    def _document_from_page(self, page: dict[str, Any]) -> SourceDocument:
        body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
        title = page.get("title") or "Confluence page"
        text = "\n".join(part for part in [title, _strip_html(body)] if part)
        version = page.get("version") or {}
        return SourceDocument(
            source=self.name,
            external_id=f"page:{page.get('id')}",
            title=title,
            text=text,
            occurred_at=version.get("createdAt") or page.get("createdAt"),
            author=((version.get("authorId") or page.get("authorId") or "")),
            url=(page.get("_links") or {}).get("webui"),
            metadata={
                "kind": "page",
                "id": page.get("id"),
                "space_id": page.get("spaceId"),
                "status": page.get("status"),
                "version": version.get("number"),
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
