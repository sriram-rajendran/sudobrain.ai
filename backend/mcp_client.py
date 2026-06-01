"""Safe MCP client configuration and tool-preview helpers."""

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
        issues = []
        if server.get("enabled", True) and not (server.get("command") or server.get("url")):
            issues.append("enabled server needs command or url")
        safe.append({
            "name": server.get("name", ""),
            "transport": server.get("transport", "stdio"),
            "command_configured": bool(server.get("command")),
            "url_configured": bool(server.get("url")),
            "enabled": server.get("enabled", True),
            "tools_declared": len(server.get("tools", [])) if isinstance(server.get("tools"), list) else 0,
            "issues": issues,
        })
    return {"servers": safe, "config_path": str(CONFIG_PATH)}


def list_mcp_tools() -> dict:
    """Return built-in and configured MCP tools without launching external servers."""
    from scripts.sudobrain_mcp_server import TOOLS

    configured = []
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except Exception:
            data = {}
        for server in data.get("servers", []) if isinstance(data, dict) else []:
            if not isinstance(server, dict):
                continue
            for tool in server.get("tools", []) if isinstance(server.get("tools"), list) else []:
                if isinstance(tool, dict):
                    configured.append({
                        "server": server.get("name", ""),
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "inputSchema": tool.get("inputSchema", {}),
                        "external": True,
                    })

    return {
        "builtin": [{**tool, "server": "sudobrain", "external": False} for tool in TOOLS],
        "configured": configured,
        "external_execution": False,
    }


def preview_tool_call(name: str, arguments: dict | None = None, server: str = "sudobrain") -> dict:
    """Preview an MCP tool call without launching subprocesses or network clients."""
    arguments = arguments or {}
    tools = list_mcp_tools()
    all_tools = tools["builtin"] + tools["configured"]
    match = next((tool for tool in all_tools if tool.get("name") == name and tool.get("server") == server), None)
    if not match:
        return {"status": "unknown_tool", "server": server, "name": name, "dry_run": True}

    return {
        "status": "preview",
        "server": server,
        "name": name,
        "arguments": arguments,
        "schema": match.get("inputSchema", {}),
        "external": bool(match.get("external")),
        "would_execute": False,
        "dry_run": True,
    }
