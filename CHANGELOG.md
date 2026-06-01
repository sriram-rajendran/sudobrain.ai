# Changelog

## Unreleased

- Added synthetic demo data loading through `scripts/load_demo_data.py` and `make demo`.
- Added local startup smoke checks through `scripts/smoke_test_startup.py` and `make smoke`.
- Added `scripts/bootstrap_local.sh` for one-command local dependency setup.
- Added `docker-compose.full.yml` for backend, Postgres, and Neo4j.
- Added JSON and Markdown knowledge export at `/knowledge/export`.
- Expanded onboarding readiness checks for local storage, Chroma, Calendar, and demo data.
- Added open-source adoption docs: architecture, data flow, feature matrix, roadmap, release checklist, and five-minute quickstart.
- Added code of conduct and GitHub issue templates.
- Added extension SDK protocols for connectors, intelligence modules, and workflow actions.
- Added a read-only local Markdown connector example.
- Added a lightweight SudoBrain MCP server scaffold and documentation.
- Added safe model-provider configuration reporting for local, OpenAI-compatible, and opt-in cloud providers.
- Added provenance, source freshness, graph export, retention preview, and chat feedback APIs.
- Added workflow templates, approval queue, trace history, and app surfaces.
- Added document library, bookmark, folder watch, webpage summary, and OCR text handoff scaffolds.
- Added sample intelligence module, sample workflow action, expanded MCP tools, and unit contract tests.
- Added local admin dashboard, audit/request log, observability status, usage analytics, CI workflow, and release docs.
- Added review queue filters, report export/share artifacts, plugin registry discovery, and MCP client status.
- Added OpenAI-compatible provider execution scaffold and a local web/PWA companion.
- Added Slack, Gmail, Fathom, and Linear fixture-shape tests plus unsigned package script.
- Added saved chat sessions, chat collections, provider switching, mobile capture, and chat-channel capture adapters.
- Added workflow graph builder scaffold and per-source privacy controls.
- Added docs/release workflows, release manifest, backend packaging spec, and public-safe README screenshots.
- Added non-destructive release readiness audit for repo artifacts and external launch blockers.
