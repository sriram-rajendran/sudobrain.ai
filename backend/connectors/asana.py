"""Read-only Asana connector."""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class AsanaConnector:
    name = "asana"
    api_base = "https://app.asana.com/api/1.0"

    def __init__(
        self,
        token: str | None = None,
        workspace_gid: str | None = None,
        project_gid: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("SUDOBRAIN_ASANA_TOKEN", "")
        self.workspace_gid = workspace_gid if workspace_gid is not None else os.getenv("SUDOBRAIN_ASANA_WORKSPACE_GID", "")
        self.project_gid = project_gid if project_gid is not None else os.getenv("SUDOBRAIN_ASANA_PROJECT_GID", "")
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

    def health(self) -> dict[str, Any]:
        if not self.token:
            return {
                "name": self.name,
                "ok": False,
                "token_configured": False,
                "detail": "SUDOBRAIN_ASANA_TOKEN not configured",
            }
        try:
            user = self._get("/" + "users" + "/me").get("data", {})
            return {
                "name": self.name,
                "ok": True,
                "token_configured": True,
                "workspace_gid": self.workspace_gid,
                "project_gid": self.project_gid,
                "user_gid": user.get("gid", ""),
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
        params = {
            "limit": limit,
            "opt_fields": ",".join([
                "gid",
                "name",
                "notes",
                "completed",
                "completed_at",
                "created_at",
                "modified_at",
                "due_on",
                "permalink_url",
                "assignee.name",
                "assignee.gid",
                "projects.name",
                "projects.gid",
                "memberships.project.name",
                "memberships.section.name",
            ]),
        }
        if self.project_gid:
            params["project"] = self.project_gid
        elif self.workspace_gid:
            params["workspace"] = self.workspace_gid
        payload = self._get("/tasks", params)
        tasks = payload.get("data", [])
        return [self._document_from_task(task) for task in tasks[:limit]]

    def _document_from_task(self, task: dict[str, Any]) -> SourceDocument:
        title = task.get("name") or "Asana task"
        assignee = (task.get("assignee") or {}).get("name", "")
        projects = [project.get("name", "") for project in task.get("projects", []) if project.get("name")]
        sections = [
            ((membership.get("section") or {}).get("name") or "")
            for membership in task.get("memberships", [])
            if (membership.get("section") or {}).get("name")
        ]
        text = "\n".join(part for part in [
            title,
            task.get("notes") or "",
            f"Completed: {bool(task.get('completed'))}",
            f"Assignee: {assignee}" if assignee else "",
            f"Due: {task.get('due_on')}" if task.get("due_on") else "",
            f"Projects: {', '.join(projects)}" if projects else "",
            f"Sections: {', '.join(sections)}" if sections else "",
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"task:{task.get('gid')}",
            title=title,
            text=text,
            occurred_at=task.get("modified_at") or task.get("created_at"),
            author=assignee,
            url=task.get("permalink_url"),
            metadata={
                "kind": "task",
                "gid": task.get("gid"),
                "completed": bool(task.get("completed")),
                "completed_at": task.get("completed_at"),
                "due_on": task.get("due_on"),
                "assignee": assignee,
                "projects": projects,
                "sections": sections,
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
