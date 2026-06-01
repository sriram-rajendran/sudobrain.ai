# Feature Matrix

| Area | Stable | Experimental | Planned |
|---|---|---|---|
| Local backend | FastAPI API, health checks, auth middleware, rate limits, local RBAC, scheduled-agent status, local request metrics | automatic source sync scheduler | packaged backend runtime |
| Storage | Postgres schema, local data directory, Markdown/JSON vault export | Chroma semantic index, Neo4j graph enrichment | editable vault import and bidirectional sync |
| macOS app | SwiftUI navigation, chat, knowledge views, onboarding | workflow and intelligence dashboards | automatic backend startup and update flow |
| Sources | recordings, Slack, Gmail, Fathom, Linear, Calendar, local repos | attachment extraction, document library, bookmarks, OCR text handoff, folder watch config, and project-context scoring | connector SDK runtime and plugin registry |
| AI | local/Ollama-oriented routing, offline search fallback, provider routing rules, provider health UI | ReACT agent, self-improvement rules, opt-in provider clients | advanced model routing UI |
| Trust | source audit, privacy docs, public repo verifier, knowledge export, reversible review action log, approval bundles, workflow approval outbox | citation cards and provenance details | advanced provenance graph UI |
| Tryability | bootstrap script, demo seed data, smoke test | full Docker Compose backend | signed release artifacts |
| Community | contributing guide, security policy, MIT license | docs pages and issue templates | hosted docs site and discussions |
| Security | token auth, viewer/editor/owner roles, encrypted local secret store | SSO configuration status | hosted/team SSO login |

Stable means the surface is intended for regular local use. Experimental means
the contract may change. Planned means the roadmap names the feature, but the
repo currently carries docs or scaffolding rather than a finished product
surface.
