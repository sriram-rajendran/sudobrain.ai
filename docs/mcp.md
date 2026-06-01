# MCP Server

SudoBrain includes a lightweight stdio JSON-RPC server for local knowledge tools:

```bash
make mcp-server
```

It exposes:

- `sudobrain_search`
- `sudobrain_tasks`
- `sudobrain_decisions`
- `sudobrain_promises`
- `sudobrain_projects`
- `sudobrain_people`
- `sudobrain_reports`

The server is intentionally dependency-light. It is a scaffold for MCP clients
and contributors before adopting a full MCP SDK.

## Client Tool Catalog

The backend can inspect MCP configuration and expose a safe tool catalog without
launching external servers:

```bash
curl http://127.0.0.1:8420/mcp/client/status
curl http://127.0.0.1:8420/mcp/client/tools
```

Tool calls can be dry-run previewed. Preview mode validates the selected tool
and echoes the arguments without running subprocesses, network clients, or
external writes:

```bash
curl -X POST http://127.0.0.1:8420/mcp/client/tools/preview \
  -H 'Content-Type: application/json' \
  -d '{"server":"sudobrain","name":"sudobrain_search","arguments":{"query":"Atlas"}}'
```

## Example Request

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

## Example Tool Call

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"sudobrain_search","arguments":{"query":"Atlas","limit":5}}}
```

Run the backend database services before calling tools that query Postgres.
