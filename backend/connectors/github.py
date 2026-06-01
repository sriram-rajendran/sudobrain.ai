"""Read-only GitHub connector.

The connector normalizes public or token-authenticated repository activity into
`SourceDocument` records. It intentionally avoids writes and redacts token
state from health output.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import requests

from backend.sdk import SourceDocument


class GitHubConnector:
    name = "github"
    api_base = "https://api.github.com"
    graphql_url = "https://api.github.com/graphql"

    def __init__(self, repo: str, token: str | None = None, session: Any | None = None) -> None:
        if "/" not in repo:
            raise ValueError("repo must use owner/name format")
        self.repo = repo.strip()
        self.owner, self.repo_name = self.repo.split("/", 1)
        self.token = token if token is not None else os.getenv("SUDOBRAIN_GITHUB_TOKEN", "")
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SudoBrain",
        }
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
        return response.json()

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            return {"skipped": "GitHub token required for GraphQL discussion access"}
        response = self.session.post(
            self.graphql_url,
            headers=self._headers(),
            json={"query": query, "variables": variables},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        try:
            repo = self._get(f"/repos/{self.repo}")
            ok = True
            detail = "reachable"
        except Exception as exc:
            repo = {}
            ok = False
            detail = str(exc)
        return {
            "name": self.name,
            "ok": ok,
            "repo": self.repo,
            "private": bool(repo.get("private", False)),
            "default_branch": repo.get("default_branch", ""),
            "token_configured": bool(self.token),
            "scopes": ["issues", "pull_requests", "reviews", "discussions", "releases", "commits", "ci_failures"],
            "detail": detail[:300],
        }

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        limit = max(1, min(limit, 100))
        documents: list[SourceDocument] = []
        documents.extend(self._fetch_issues_and_prs(limit))
        documents.extend(self._fetch_releases(max(1, limit // 5)))
        documents.extend(self._fetch_commits(max(1, limit // 3)))
        documents.extend(self._fetch_ci_runs(max(1, limit // 3)))
        documents.extend(self._fetch_discussions(max(1, limit // 5)))
        return documents[:limit]

    def _fetch_issues_and_prs(self, limit: int) -> list[SourceDocument]:
        items = self._get(
            f"/repos/{self.repo}/issues",
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
        )
        documents = []
        for item in items:
            is_pr = "pull_request" in item
            body_parts = [
                item.get("title") or "",
                item.get("body") or "",
                f"State: {item.get('state', 'unknown')}",
                f"Author: {(item.get('user') or {}).get('login', 'unknown')}",
            ]
            documents.append(
                SourceDocument(
                    source=self.name,
                    external_id=f"{'pr' if is_pr else 'issue'}:{item.get('number')}",
                    title=item.get("title") or f"GitHub item {item.get('number')}",
                    text="\n\n".join(part for part in body_parts if part),
                    occurred_at=item.get("updated_at") or item.get("created_at"),
                    author=(item.get("user") or {}).get("login"),
                    url=item.get("html_url"),
                    metadata={
                        "repo": self.repo,
                        "kind": "pull_request" if is_pr else "issue",
                        "number": item.get("number"),
                        "labels": [label.get("name") for label in item.get("labels", []) if label.get("name")],
                    },
                )
            )
            if is_pr:
                documents.extend(self._fetch_pr_reviews(item.get("number"), limit=5))
        return documents

    def _fetch_pr_reviews(self, number: int | None, limit: int = 5) -> list[SourceDocument]:
        if not number:
            return []
        try:
            reviews = self._get(
                f"/repos/{self.repo}/pulls/{number}/reviews",
                {"per_page": max(1, min(limit, 100))},
            )
        except Exception:
            return []
        documents = []
        for review in reviews:
            text = "\n\n".join(
                part for part in [
                    review.get("body") or "",
                    f"State: {review.get('state', 'unknown')}",
                    f"Reviewer: {(review.get('user') or {}).get('login', 'unknown')}",
                ]
                if part
            )
            if not text:
                continue
            documents.append(
                SourceDocument(
                    source=self.name,
                    external_id=f"pr_review:{number}:{review.get('id')}",
                    title=f"Review on PR #{number}",
                    text=text,
                    occurred_at=review.get("submitted_at"),
                    author=(review.get("user") or {}).get("login"),
                    url=review.get("html_url"),
                    metadata={"repo": self.repo, "kind": "pull_request_review", "number": number},
                )
            )
        return documents

    def _fetch_releases(self, limit: int) -> list[SourceDocument]:
        try:
            releases = self._get(f"/repos/{self.repo}/releases", {"per_page": max(1, min(limit, 100))})
        except Exception:
            return []
        return [
            SourceDocument(
                source=self.name,
                external_id=f"release:{release.get('id')}",
                title=release.get("name") or release.get("tag_name") or "GitHub release",
                text="\n\n".join(part for part in [release.get("name") or "", release.get("body") or ""] if part),
                occurred_at=release.get("published_at") or release.get("created_at"),
                author=(release.get("author") or {}).get("login"),
                url=release.get("html_url"),
                metadata={"repo": self.repo, "kind": "release", "tag": release.get("tag_name")},
            )
            for release in releases
        ]

    def _fetch_commits(self, limit: int) -> list[SourceDocument]:
        try:
            commits = self._get(f"/repos/{self.repo}/commits", {"per_page": max(1, min(limit, 100))})
        except Exception:
            return []
        documents = []
        for item in commits:
            commit = item.get("commit") or {}
            author = commit.get("author") or {}
            documents.append(
                SourceDocument(
                    source=self.name,
                    external_id=f"commit:{item.get('sha')}",
                    title=(commit.get("message") or "Commit").splitlines()[0],
                    text=commit.get("message") or "",
                    occurred_at=author.get("date"),
                    author=author.get("name") or ((item.get("author") or {}).get("login")),
                    url=item.get("html_url"),
                    metadata={"repo": self.repo, "kind": "commit", "sha": item.get("sha")},
                )
            )
        return documents

    def _fetch_ci_runs(self, limit: int) -> list[SourceDocument]:
        try:
            payload = self._get(
                f"/repos/{self.repo}/actions/runs",
                {"per_page": max(1, min(limit, 100)), "status": "completed"},
            )
        except Exception:
            return []
        documents = []
        for run in payload.get("workflow_runs", []):
            conclusion = run.get("conclusion") or "unknown"
            text = "\n".join([
                f"Workflow: {run.get('name', 'unknown')}",
                f"Status: {run.get('status', 'unknown')}",
                f"Conclusion: {conclusion}",
                f"Branch: {run.get('head_branch', '')}",
                f"Commit: {run.get('head_sha', '')}",
            ])
            documents.append(
                SourceDocument(
                    source=self.name,
                    external_id=f"ci_run:{run.get('id')}",
                    title=f"{run.get('name', 'Workflow')} {conclusion}",
                    text=text,
                    occurred_at=run.get("updated_at") or run.get("created_at"),
                    author=(run.get("actor") or {}).get("login"),
                    url=run.get("html_url"),
                    metadata={"repo": self.repo, "kind": "ci_failure" if conclusion == "failure" else "ci_run"},
                )
            )
        return documents

    def _fetch_discussions(self, limit: int) -> list[SourceDocument]:
        query = """
        query SudoBrainDiscussions($owner: String!, $name: String!, $first: Int!) {
          repository(owner: $owner, name: $name) {
            discussions(first: $first, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                bodyText
                url
                updatedAt
                author { login }
              }
            }
          }
        }
        """
        try:
            payload = self._graphql(query, {"owner": self.owner, "name": self.repo_name, "first": max(1, min(limit, 50))})
        except Exception:
            return []
        nodes = (((payload.get("data") or {}).get("repository") or {}).get("discussions") or {}).get("nodes") or []
        return [
            SourceDocument(
                source=self.name,
                external_id=f"discussion:{item.get('number')}",
                title=item.get("title") or "GitHub discussion",
                text="\n\n".join(part for part in [item.get("title") or "", item.get("bodyText") or ""] if part),
                occurred_at=item.get("updatedAt"),
                author=(item.get("author") or {}).get("login"),
                url=item.get("url"),
                metadata={"repo": self.repo, "kind": "discussion", "number": item.get("number")},
            )
            for item in nodes
        ]


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
