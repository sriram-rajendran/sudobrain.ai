#!/usr/bin/env python3
"""Tiny JSON-RPC MCP-style server for local SudoBrain knowledge tools.

It supports stdio JSON-RPC requests for `tools/list` and `tools/call`. The
implementation is dependency-light so contributors can inspect and extend it
before adopting a full MCP SDK.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TOOLS = [
    {
        "name": "sudobrain_search",
        "description": "Search transcript segments with local full-text search.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "sudobrain_tasks",
        "description": "List pending action items.",
        "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}}},
    },
    {
        "name": "sudobrain_decisions",
        "description": "List recent decisions.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "sudobrain_promises",
        "description": "List pending promises.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "sudobrain_projects",
        "description": "List known projects.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
]


def result(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}]}


def call_tool(name: str, arguments: dict[str, Any]) -> dict:
    from backend.storage import database as db

    if name == "sudobrain_search":
        query = str(arguments.get("query", ""))
        limit = int(arguments.get("limit", 10))
        return result(db.search_transcripts(query, limit=limit))

    if name == "sudobrain_tasks":
        project = arguments.get("project") or None
        return result(db.get_pending_action_items(project=project))

    conn = db.get_connection()
    try:
        limit = min(int(arguments.get("limit", 10)), 50)
        if name == "sudobrain_decisions":
            rows = conn.execute(
                "SELECT id, text, made_by, project, created_at FROM decisions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return result([dict(row) for row in rows])
        if name == "sudobrain_promises":
            rows = conn.execute(
                "SELECT id, promised_by_name, promised_to_name, description, due_date, status FROM promises WHERE status='pending' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return result([dict(row) for row in rows])
        if name == "sudobrain_projects":
            rows = conn.execute(
                "SELECT id, name, description, status, created_at FROM projects ORDER BY name LIMIT ?",
                (limit,),
            ).fetchall()
            return result([dict(row) for row in rows])
    finally:
        conn.close()

    raise ValueError(f"Unknown tool: {name}")


def handle(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    request_id = request.get("id")
    try:
        if method == "initialize":
            payload = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "sudobrain", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            payload = {"tools": TOOLS}
        elif method == "tools/call":
            params = request.get("params") or {}
            payload = call_tool(params.get("name", ""), params.get("arguments") or {})
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": payload}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            response = handle(request)
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
