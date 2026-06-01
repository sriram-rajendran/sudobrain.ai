"""Read-only Jira connector."""

from __future__ import annotations

import base64
import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class JiraConnector:
    name = "jira"

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
        bearer_token: str | None = None,
        jql: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("SUDOBRAIN_JIRA_BASE_URL", "")).rstrip("/")
        self.email = email if email is not None else os.getenv("SUDOBRAIN_JIRA_EMAIL", "")
        self.token = token if token is not None else os.getenv("SUDOBRAIN_JIRA_TOKEN", "")
        self.bearer_token = bearer_token if bearer_token is not None else os.getenv("SUDOBRAIN_JIRA_BEARER_TOKEN", "")
        self.jql = jql or os.getenv("SUDOBRAIN_JIRA_JQL", "ORDER BY updated DESC")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "SudoBrain"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.email and self.token:
            raw = f"{self.email}:{self.token}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", headers=self._headers(), params=params or {}, timeout=30)
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
                "detail": "Jira base URL and read-only token are required",
            }
        try:
            myself = self._get("/rest/api/3/myself")
            return {
                "name": self.name,
                "ok": True,
                "base_url_configured": True,
                "token_configured": True,
                "account_type": myself.get("accountType", ""),
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
        payload = self._get(
            "/rest/api/3/search",
            {
                "jql": self.jql,
                "maxResults": limit,
                "fields": "summary,description,status,assignee,reporter,project,issuetype,priority,labels,updated,created,parent,comment,sprint,customfield_10020",
            },
        )
        issues = payload.get("issues", [])
        return [self._document_from_issue(issue) for issue in issues[:limit]]

    def _document_from_issue(self, issue: dict[str, Any]) -> SourceDocument:
        fields = issue.get("fields") or {}
        key = issue.get("key") or issue.get("id") or "issue"
        title = fields.get("summary") or key
        description = _adf_to_text(fields.get("description"))
        comments = _comments_to_text(((fields.get("comment") or {}).get("comments") or []))
        status = (fields.get("status") or {}).get("name", "")
        assignee = (fields.get("assignee") or {}).get("displayName", "")
        reporter = (fields.get("reporter") or {}).get("displayName", "")
        priority = (fields.get("priority") or {}).get("name", "")
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        project = (fields.get("project") or {}).get("key", "")
        parent = fields.get("parent") or {}
        sprints = fields.get("customfield_10020") or fields.get("sprint") or []
        text = "\n".join(part for part in [
            title,
            f"Key: {key}",
            f"Type: {issue_type}",
            f"Status: {status}",
            f"Priority: {priority}",
            f"Assignee: {assignee}",
            f"Reporter: {reporter}",
            f"Project: {project}",
            f"Parent: {parent.get('key', '')}" if parent else "",
            description,
            comments,
        ] if part)
        return SourceDocument(
            source=self.name,
            external_id=f"issue:{key}",
            title=title,
            text=text,
            occurred_at=fields.get("updated") or fields.get("created"),
            author=reporter or assignee,
            url=f"{self.base_url}/browse/{key}" if self.base_url and key else None,
            metadata={
                "kind": "issue",
                "id": issue.get("id"),
                "key": key,
                "issue_type": issue_type,
                "status": status,
                "priority": priority,
                "assignee": assignee,
                "reporter": reporter,
                "project": project,
                "labels": fields.get("labels") or [],
                "parent": parent.get("key") if parent else None,
                "sprints": [_sprint_name(item) for item in sprints] if isinstance(sprints, list) else [],
            },
        )


def _adf_to_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        pieces = []
        if "text" in value:
            pieces.append(str(value.get("text") or ""))
        for child in value.get("content") or []:
            text = _adf_to_text(child)
            if text:
                pieces.append(text)
        return " ".join(part for part in pieces if part).strip()
    if isinstance(value, list):
        return " ".join(_adf_to_text(item) for item in value).strip()
    return str(value)


def _comments_to_text(comments: list[dict[str, Any]]) -> str:
    lines = []
    for comment in comments[:20]:
        author = (comment.get("author") or {}).get("displayName", "unknown")
        body = _adf_to_text(comment.get("body"))
        if body:
            lines.append(f"Comment by {author}: {body}")
    return "\n".join(lines)


def _sprint_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "")
    return str(value)


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
