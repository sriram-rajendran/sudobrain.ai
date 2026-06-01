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
- Provenance APIs for decisions, promises, people, and graph edges: started.
- Confidence scoring for stored knowledge: started through provenance responses.
- Portable graph export: started via `/graph/export`.
- Retention policy controls: started via `/privacy/retention`.
- Review queue filters by source, type, confidence, project, and age: planned.
- Source freshness dashboard: backend started via `/sources/freshness`.

## P2: Make SudoBrain Extensible

- Connector SDK: started in `backend/sdk/interfaces.py`.
- Intelligence module SDK: started in `backend/sdk/interfaces.py`.
- Workflow action SDK: started in `backend/sdk/interfaces.py`.
- Local Markdown connector example: shipped in `backend/connectors/local_markdown.py`.
- MCP server for SudoBrain knowledge: started in `scripts/sudobrain_mcp_server.py`.
- Sample intelligence module: shipped in `backend/intelligence/sample_module.py`.
- Sample workflow action: shipped in `backend/actions/sample_workflow_action.py`.
- MCP client/tool support: planned.
- Plugin developer documentation: shipped in `docs/plugin-development.md`.

## P3: Make SudoBrain Productive

- Workflow templates: started via `/workflows/templates`.
- Scheduled agent runner: existing heartbeat evaluation, UI still planned.
- Agent run history and replay: workflow history started, full replay planned.
- Tool-call trace viewer: workflow trace backend and UI started.
- Approval steps before external writes: approval queue scaffold started.
- Report sharing/export: planned.

## P4: Make SudoBrain Community-Ready

- Web/PWA companion: planned.
- Provider settings UI: started through `/models/status` safe configuration reporting.
- OpenAI-compatible, Anthropic, Gemini, OpenRouter, Groq, Bedrock, and LM Studio configuration: started in `.env.example` and `backend/ai/providers.py`.
- Usage analytics: planned.
- Admin/debug dashboard: started via `/admin/dashboard` and the macOS Admin view.
- Local audit/request logs: started via `/admin/audit-log` and `/admin/request-log`.
- Observability status: started via `/observability/status`.
- Fixture-based integration tests: started.
- Release process and changelog: started, with CI workflow and release notes template.

## Product Principles

- Local-first by default.
- Cloud providers are opt-in.
- External integrations stay read-only unless writes are explicit, permissioned, and auditable.
- Every generated answer should be traceable to sources.
- Every extracted fact should be reviewable.
- Every connector should be replaceable.
- Advanced features should degrade gracefully when local services are missing.
