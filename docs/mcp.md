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

The server is intentionally dependency-light. It is a scaffold for MCP clients
and contributors before adopting a full MCP SDK.

## Example Request

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

## Example Tool Call

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"sudobrain_search","arguments":{"query":"Atlas","limit":5}}}
```

Run the backend database services before calling tools that query Postgres.
