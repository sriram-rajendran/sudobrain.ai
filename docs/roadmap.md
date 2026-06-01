# Roadmap

SudoBrain's open-source positioning is local-first AI memory and intelligence
for real work: meetings, Slack, Gmail, Linear, code repositories, people,
decisions, promises, and project risk.

## P0: Make SudoBrain Tryable

- Synthetic demo data generator: shipped in `scripts/load_demo_data.py`.
- `make demo`: shipped.
- One-command local bootstrap: shipped in `scripts/bootstrap_local.sh`.
- Full local startup smoke test: shipped in `scripts/smoke_test_startup.py`.
- Full-app Docker Compose backend path: shipped in `docker-compose.full.yml`.
- Try in 5 minutes guide: shipped in `docs/try-sudobrain-in-5-minutes.md`.
- README adoption path: shipped.

## P1: Make SudoBrain Trustworthy

- Source citation metadata for chat search results: started.
- JSON and Markdown knowledge export: shipped via `/knowledge/export`.
- Source audit endpoint: existing.
- Provenance UI for decisions, promises, people, and graph edges: planned.
- Review queue filters by source, type, confidence, project, and age: planned.
- Source freshness dashboard: planned.

## P2: Make SudoBrain Extensible

- Connector SDK: started in `backend/sdk/interfaces.py`.
- Intelligence module SDK: started in `backend/sdk/interfaces.py`.
- Workflow action SDK: started in `backend/sdk/interfaces.py`.
- Local Markdown connector example: shipped in `backend/connectors/local_markdown.py`.
- MCP server for SudoBrain knowledge: started in `scripts/sudobrain_mcp_server.py`.
- MCP client/tool support: planned.
- Plugin developer documentation: shipped in `docs/plugin-development.md`.

## P3: Make SudoBrain Productive

- Workflow templates: planned.
- Scheduled agent runner: planned.
- Agent run history and replay: planned.
- Tool-call trace viewer: planned.
- Approval steps before external writes: planned.
- Report sharing/export: planned.

## P4: Make SudoBrain Community-Ready

- Web/PWA companion: planned.
- Provider settings UI: planned.
- OpenAI-compatible, Anthropic, Gemini, OpenRouter, Groq, Bedrock, and LM Studio configuration: planned.
- Usage analytics: planned.
- Admin/debug dashboard: planned.
- Fixture-based integration tests: planned.
- Release process and changelog: started.

## Product Principles

- Local-first by default.
- Cloud providers are opt-in.
- External integrations stay read-only unless writes are explicit, permissioned, and auditable.
- Every generated answer should be traceable to sources.
- Every extracted fact should be reviewable.
- Every connector should be replaceable.
- Advanced features should degrade gracefully when local services are missing.
