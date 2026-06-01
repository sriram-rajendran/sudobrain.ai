"""MCP client configuration scaffold."""

from __future__ import annotations

import json
import os
from pathlib import Path


CONFIG_PATH = Path(os.getenv("SUDOBRAIN_MCP_CONFIG", "~/.sudobrain/mcp_servers.json")).expanduser()


def load_mcp_servers() -> dict:
    if not CONFIG_PATH.exists():
        return {"servers": [], "config_path": str(CONFIG_PATH)}
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception as exc:
        return {"servers": [], "config_path": str(CONFIG_PATH), "error": str(exc)}
    servers = data.get("servers", []) if isinstance(data, dict) else []
    safe = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        safe.append({
            "name": server.get("name", ""),
            "transport": server.get("transport", "stdio"),
            "command_configured": bool(server.get("command")),
            "url_configured": bool(server.get("url")),
            "enabled": server.get("enabled", True),
        })
    return {"servers": safe, "config_path": str(CONFIG_PATH)}
