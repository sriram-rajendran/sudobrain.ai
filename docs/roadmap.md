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

- Source citation metadata for chat search results: shipped for local search and chat cards.
- JSON and Markdown knowledge export: shipped via `/knowledge/export`.
- Source audit endpoint: existing.
- Provenance APIs for decisions, promises, people, and graph edges: started.
- Confidence scoring for stored knowledge: started through provenance responses.
- Portable graph export: started via `/graph/export`.
- Retention policy controls: started via `/privacy/retention`.
- Per-source privacy controls: shipped via `/privacy/sources`.
- Source freshness dashboard: backend started via `/sources/freshness`.
- Review queue filters by source, type, confidence, project, and age: shipped in `/review/queue`.
- Reversible extraction review actions: shipped via `/review/actions` and undo endpoints.
- Editable Markdown/JSON knowledge vault export: shipped via `/knowledge/vault/export`.

## P2: Make SudoBrain Extensible

- Connector SDK: started in `backend/sdk/interfaces.py`.
- Intelligence module SDK: started in `backend/sdk/interfaces.py`.
- Workflow action SDK: started in `backend/sdk/interfaces.py`.
- Local Markdown connector example: shipped in `backend/connectors/local_markdown.py`.
- MCP server for SudoBrain knowledge: started in `scripts/sudobrain_mcp_server.py`.
- Sample intelligence module: shipped in `backend/intelligence/sample_module.py`.
- Sample workflow action: shipped in `backend/actions/sample_workflow_action.py`.
- MCP client/tool support: config/status scaffold started via `/mcp/client/status`.
- Plugin registry: discovery scaffold started via `/plugins`.
- Plugin developer documentation: shipped in `docs/plugin-development.md`.

## P3: Make SudoBrain Productive

- Workflow templates: started via `/workflows/templates`.
- Scheduled agent runner: shipped via `/scheduler/status`, `/heartbeat/trigger`, `/intelligence/run-now`, and the Admin scheduled agents panel.
- Agent run history and replay: shipped via `/workflows/log`, `/workflows/log/{log_id}/replay`, and the macOS workflow view.
- Tool-call trace viewer: workflow trace backend and UI started.
- Approval steps before external writes: approval queue scaffold started.
- Visual/no-code workflow builder: started via `/workflows/graph` and `web-companion/workflow-builder.html`.
- Report sharing/export: local Markdown/JSON export and share artifacts shipped.

## P4: Make SudoBrain Community-Ready

- Web/PWA companion: shipped for local search, streaming chat, quick capture, reports, and vault export in `web-companion/`.
- Provider settings UI: started through `/models/status` safe configuration reporting.
- Per-task provider routing rules: shipped via `/models/routing-rules` and `/models/route`.
- OpenAI-compatible, OpenRouter, LM Studio, Anthropic, Gemini, Groq, and Bedrock execution scaffolds: shipped.
- Usage analytics: expanded local counts and trends shipped via `/usage/analytics`.
- Admin/debug dashboard: started via `/admin/dashboard` and the macOS Admin view.
- Local audit/request logs: started via `/admin/audit-log` and `/admin/request-log`.
- Observability status: started via `/observability/status`.
- Local RBAC enforcement: shipped for owner/editor/viewer roles.
- API rate limits: shipped via `SUDOBRAIN_RATE_LIMIT_PER_MINUTE`.
- Encrypted local secrets store: shipped via `/security/secrets`.
- Fixture-based integration tests: shipped for Slack, Gmail, Fathom, and Linear fixture shapes.
- Release process and changelog: started, with CI workflow, release notes template, and unsigned package script.
- Docs hosting workflow: shipped via GitHub Pages workflow.
- Release artifacts workflow: shipped as draft release workflow with unsigned artifacts and optional signing-secret hook.
- README screenshots: synthetic public-safe screenshots shipped; captured GIFs still require running the app.

## Cross-Platform And Chat UX

- Mobile/non-Mac capture: shipped via `/capture/mobile`.
- Chat-channel capture adapter: shipped via `/capture/channel/{channel_name}`.
- Web companion quick-capture surface: shipped in `web-companion/`.
- Chat streaming endpoint: shipped via `/chat/stream`.
- Saved chat sessions and collections: shipped via `/chat/sessions`.
- Prompt/provider switcher: shipped in the macOS Chat view.

## Product Principles

- Local-first by default.
- Cloud providers are opt-in.
- External integrations stay read-only unless writes are explicit, permissioned, and auditable.
- Every generated answer should be traceable to sources.
- Every extracted fact should be reviewable.
- Every connector should be replaceable.
- Advanced features should degrade gracefully when local services are missing.
