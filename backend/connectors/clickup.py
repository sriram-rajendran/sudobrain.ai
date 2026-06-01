"""Read-only ClickUp connector."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class ClickUpConnector:
    name = "clickup"
    api_base = "https://api.clickup.com/api/v2"

    def __init__(
        self,
        token: str | None = None,
        team_id: str | None = None,
        list_id: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_CLICKUP_TOKEN", "")
        self.team_id = team_id if team_id is not None else os.getenv("SUDOBRAIN_CLICKUP_TEAM_ID", "")
        self.list_id = list_id if list_id is not None else os.getenv("SUDOBRAIN_CLICKUP_LIST_ID", "")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.api_base}{path}", headers=self._headers(), params=params or {}, timeout=30)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_CLICKUP_TOKEN not configured",
            }
        try:
            user = self._get("/user").get("user", {})
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "team_id": self.team_id,
                "list_id": self.list_id,
                "user": user.get("username", ""),
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
        if self.list_id:
            payload = self._get(f"/list/{self.list_id}/task", {"page": 0, "subtasks": "true", "include_closed": "true"})
        elif self.team_id:
            payload = self._get(f"/team/{self.team_id}/task", {"page": 0, "subtasks": "true", "include_closed": "true"})
        else:
            payload = {"tasks": []}
        tasks = payload.get("tasks", [])
        return [self._document_from_task(task) for task in tasks[:limit]]

    def _document_from_task(self, task: dict[str, Any]) -> SourceDocument:
        title = task.get("name") or "ClickUp task"
        status = (task.get("status") or {}).get("status", "")
        assignees = [
            item.get("username") or item.get("email") or ""
            for item in task.get("assignees", [])
            if item.get("username") or item.get("email")
        ]
        tags = [tag.get("name") for tag in task.get("tags", []) if tag.get("name")]
        priority = task.get("priority") or {}
        text = "\n".join(part for part in [
            title,
            task.get("description") or task.get("text_content") or "",
            f"Status: {status}" if status else "",
            f"Priority: {priority.get('priority')}" if priority.get("priority") else "",
            f"Assignees: {', '.join(assignees)}" if assignees else "",
            f"Tags: {', '.join(tags)}" if tags else "",
            f"Due: {task.get('due_date')}" if task.get("due_date") else "",
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"task:{task.get('id')}",
            title=title,
            text=text,
            occurred_at=task.get("date_updated") or task.get("date_created"),
            author=", ".join(assignees),
            url=task.get("url"),
            metadata={
                "kind": "task",
                "id": task.get("id"),
                "status": status,
                "priority": priority.get("priority"),
                "assignees": assignees,
                "tags": tags,
                "list_id": ((task.get("list") or {}).get("id") or self.list_id),
                "folder_id": (task.get("folder") or {}).get("id"),
                "space_id": (task.get("space") or {}).get("id"),
                "due_date": task.get("due_date"),
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
