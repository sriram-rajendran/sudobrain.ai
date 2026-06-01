"""Safe runtime helpers for built-in extension SDK examples."""

from __future__ import annotations

from backend.actions.sample_workflow_action import DraftNotificationAction
from backend.connectors.local_markdown import LocalMarkdownConnector
from backend.intelligence.sample_module import KeywordRiskModule
from backend.plugins.registry import BUILTIN_PLUGINS, discover_plugins
from backend.sdk import SourceDocument


def list_extensions() -> dict:
    registry = discover_plugins()
    return {
        "builtins": BUILTIN_PLUGINS,
        "external": registry.get("external", []),
        "runtime": {
            "connectors": ["local_markdown"],
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
