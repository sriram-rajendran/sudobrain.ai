"""Read-only Google Drive connector for Docs, Sheets, Slides, and files."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


class GoogleDriveConnector:
    name = "google_drive"
    api_base = "https://www.googleapis.com/drive/v3"

    def __init__(self, token: str | None = None, query: str | None = None, session: Any | None = None) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_GOOGLE_DRIVE_TOKEN", "")
        self.query = query or os.getenv("SUDOBRAIN_GOOGLE_DRIVE_QUERY", "trashed=false")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{self.api_base}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
        if "application/json" in content_type or hasattr(response, "json"):
            try:
                return response.json()
            except Exception:
                pass
        return getattr(response, "text", "")

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_GOOGLE_DRIVE_TOKEN not configured",
            }
        try:
            about = self._get("/about", {"fields": "user"})
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "user": ((about.get("user") or {}).get("emailAddress") or ""),
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
        payload = self._get(
            "/files",
            {
                "pageSize": limit,
                "q": self.query,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,webViewLink,modifiedTime,createdTime,owners(emailAddress,displayName))",
            },
        )
        files = payload.get("files", []) if isinstance(payload, dict) else []
        return [self._document_from_file(item) for item in files[:limit]]

    def _document_from_file(self, item: dict[str, Any]) -> SourceDocument:
        file_id = str(item.get("id") or "")
        mime_type = item.get("mimeType") or "application/octet-stream"
        title = item.get("name") or file_id or "Google Drive file"
        text = "\n".join(part for part in [
            title,
            f"Mime type: {mime_type}",
            self._export_text(file_id, mime_type),
        ] if part)
        owner = ""
        owners = item.get("owners") or []
        if owners:
            owner = owners[0].get("emailAddress") or owners[0].get("displayName") or ""
        return SourceDocument(
            source=self.name,
            external_id=f"file:{file_id}",
            title=title,
            text=text,
            occurred_at=item.get("modifiedTime") or item.get("createdTime"),
            author=owner,
            url=item.get("webViewLink"),
            metadata={
                "kind": _kind_for_mime(mime_type),
                "id": file_id,
                "mime_type": mime_type,
                "created_time": item.get("createdTime"),
                "modified_time": item.get("modifiedTime"),
            },
        )

    def _export_text(self, file_id: str, mime_type: str) -> str:
        export_type = EXPORT_MIME_TYPES.get(mime_type)
        if not file_id or not export_type:
            return ""
        try:
            text = self._get(f"/files/{file_id}/export", {"mimeType": export_type})
        except Exception:
            return ""
        return text if isinstance(text, str) else ""


def _kind_for_mime(mime_type: str) -> str:
    if mime_type.endswith(".document"):
        return "doc"
    if mime_type.endswith(".spreadsheet"):
        return "sheet"
    if mime_type.endswith(".presentation"):
        return "slide"
    if mime_type == "application/pdf":
        return "pdf"
    return "file"


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
