"""Safe runtime helpers for built-in extension SDK examples."""

from __future__ import annotations

from backend.actions.sample_workflow_action import DraftNotificationAction
from backend.connectors.asana import AsanaConnector, preview_documents as preview_asana_documents
from backend.connectors.catalog import list_source_connectors
from backend.connectors.clickup import ClickUpConnector, preview_documents as preview_clickup_documents
from backend.connectors.confluence import ConfluenceConnector, preview_documents as preview_confluence_documents
from backend.connectors.google_drive import GoogleDriveConnector, preview_documents as preview_drive_documents
from backend.connectors.github import GitHubConnector, preview_documents
from backend.connectors.jira import JiraConnector, preview_documents as preview_jira_documents
from backend.connectors.local_markdown import LocalMarkdownConnector
from backend.connectors.microsoft_teams import MicrosoftTeamsConnector, preview_documents as preview_teams_documents
from backend.connectors.monday import MondayConnector, preview_documents as preview_monday_documents
from backend.connectors.notion import NotionConnector, preview_documents as preview_notion_documents
from backend.connectors.trello import TrelloConnector, preview_documents as preview_trello_documents
from backend.intelligence.sample_module import KeywordRiskModule
from backend.plugins.registry import BUILTIN_PLUGINS, discover_plugins
from backend.sdk import SourceDocument


def list_extensions() -> dict:
    registry = discover_plugins()
    return {
        "builtins": BUILTIN_PLUGINS,
        "external": registry.get("external", []),
        "runtime": {
            "connectors": ["local_markdown", "github", "notion", "google_drive", "confluence", "jira", "asana", "trello", "clickup", "monday", "microsoft_teams"],
            "source_catalog": list_source_connectors(),
            "intelligence_modules": ["keyword_risk"],
            "workflow_actions": ["draft_notification"],
            "dynamic_external_execution": False,
        },
    }


def local_markdown_preview(root: str, glob: str = "**/*.md", limit: int = 25) -> dict:
    connector = LocalMarkdownConnector(root, glob=glob or "**/*.md")
    health = connector.health()
    documents = []
    if health.get("ok"):
        for document in connector.fetch(limit=max(1, min(limit, 100))):
            documents.append({
                "source": document.source,
                "external_id": document.external_id,
                "title": document.title,
                "url": document.url,
                "characters": len(document.text),
                "preview": document.text[:500],
                "metadata": document.metadata,
            })
    return {"connector": connector.name, "health": health, "documents": documents}


def github_preview(repo: str, limit: int = 25, token: str | None = None) -> dict:
    connector = GitHubConnector(repo, token=token)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def notion_preview(limit: int = 25, token: str | None = None) -> dict:
    connector = NotionConnector(token=token)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_notion_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def google_drive_preview(limit: int = 25, token: str | None = None, query: str | None = None) -> dict:
    connector = GoogleDriveConnector(token=token, query=query)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_drive_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def confluence_preview(
    base_url: str | None = None,
    email: str | None = None,
    token: str | None = None,
    bearer_token: str | None = None,
    space_id: str | None = None,
    limit: int = 25,
) -> dict:
    connector = ConfluenceConnector(
        base_url=base_url,
        email=email,
        token=token,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_confluence_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def jira_preview(
    base_url: str | None = None,
    email: str | None = None,
    token: str | None = None,
    bearer_token: str | None = None,
    jql: str | None = None,
    limit: int = 25,
) -> dict:
    connector = JiraConnector(
        base_url=base_url,
        email=email,
        token=token,
        bearer_token=bearer_token,
        jql=jql,
    )
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_jira_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def asana_preview(
    token: str | None = None,
    workspace_gid: str | None = None,
    project_gid: str | None = None,
    limit: int = 25,
) -> dict:
    connector = AsanaConnector(token=token, workspace_gid=workspace_gid, project_gid=project_gid)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_asana_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def trello_preview(
    api_key: str | None = None,
    token: str | None = None,
    board_id: str | None = None,
    limit: int = 25,
) -> dict:
    connector = TrelloConnector(api_key=api_key, token=token, board_id=board_id)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_trello_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def clickup_preview(
    token: str | None = None,
    team_id: str | None = None,
    list_id: str | None = None,
    limit: int = 25,
) -> dict:
    connector = ClickUpConnector(token=token, team_id=team_id, list_id=list_id)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_clickup_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def monday_preview(
    token: str | None = None,
    board_ids: str | list[str] | None = None,
    limit: int = 25,
) -> dict:
    connector = MondayConnector(token=token, board_ids=board_ids)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_monday_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def microsoft_teams_preview(
    token: str | None = None,
    team_id: str | None = None,
    channel_id: str | None = None,
    chat_id: str | None = None,
    limit: int = 25,
) -> dict:
    connector = MicrosoftTeamsConnector(token=token, team_id=team_id, channel_id=channel_id, chat_id=chat_id)
    health = connector.health()
    documents = []
    if health.get("ok"):
        documents = preview_teams_documents(connector.fetch(limit=max(1, min(limit, 100))))
    return {"connector": connector.name, "health": health, "documents": documents}


def keyword_risk_preview(documents: list[dict], limit: int = 50) -> dict:
    normalized = [
        SourceDocument(
            source=str(item.get("source") or "preview"),
            external_id=str(item.get("external_id") or index),
            title=str(item.get("title") or "Preview"),
            text=str(item.get("text") or item.get("preview") or ""),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        )
        for index, item in enumerate(documents[: max(1, min(limit, 100))], start=1)
    ]
    module = KeywordRiskModule()
    items = [
        {
            "kind": item.kind,
            "text": item.text,
            "confidence": item.confidence,
            "source_id": item.source_id,
            "project": item.project,
            "people": list(item.people),
            "metadata": item.metadata,
        }
        for item in module.analyze(normalized)
    ]
    return {"module": module.name, "items": items}


def workflow_action_preview(payload: dict) -> dict:
    action = DraftNotificationAction()
    result = action.run(payload, dry_run=True)
    return {
        "action": action.name,
        "status": result.status,
        "message": result.message,
        "data": result.data,
        "requires_approval": result.requires_approval,
        "dry_run": True,
    }
