"""Static and filesystem-backed plugin registry.

The registry is intentionally conservative: it discovers manifests and reports
capabilities, but does not execute plugin code dynamically yet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


BUILTIN_PLUGINS = [
    {
        "id": "local_markdown",
        "name": "Local Markdown Connector",
        "type": "connector",
        "module": "backend.connectors.local_markdown",
        "status": "available",
    },
    {
        "id": "keyword_risk",
        "name": "Keyword Risk Intelligence Module",
        "type": "intelligence_module",
        "module": "backend.intelligence.sample_module",
        "status": "available",
    },
    {
        "id": "draft_notification",
        "name": "Draft Notification Workflow Action",
        "type": "workflow_action",
        "module": "backend.actions.sample_workflow_action",
        "status": "available",
    },
]


def plugin_paths() -> list[Path]:
    raw = os.getenv("SUDOBRAIN_PLUGIN_PATHS", "")
    return [Path(item).expanduser() for item in raw.split(":") if item.strip()]


def discover_plugins() -> dict:
    external = []
    for root in plugin_paths():
        if not root.exists():
            continue
        for manifest in root.glob("*/plugin.json"):
            try:
                data = json.loads(manifest.read_text())
                data["manifest_path"] = str(manifest)
                data.setdefault("status", "discovered")
                external.append(data)
            except Exception as exc:
                external.append({"manifest_path": str(manifest), "status": "invalid", "error": str(exc)})
    return {
        "builtins": BUILTIN_PLUGINS,
        "external": external,
        "plugin_paths": [str(path) for path in plugin_paths()],
        "dynamic_loading": False,
    }
