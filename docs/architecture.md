# Architecture

SudoBrain is a local-first work intelligence app with a native macOS client and
a local FastAPI backend.

```mermaid
flowchart LR
  app["macOS SwiftUI app"] --> api["FastAPI backend"]
  ext["Browser extension"] --> api
  api --> pg["Postgres"]
  api --> graph["Neo4j"]
  api --> vector["Chroma vector store"]
  api --> llm["Local/Ollama or opt-in provider"]
  sources["Read-only sources: Slack, Gmail, Fathom, Linear, Calendar, Git repos"] --> api
  api --> exports["JSON and Markdown exports"]
```

## Local-First Boundaries

- External sync paths are read-only by default.
- The backend listens locally for desktop use.
- Postgres stores raw source copies and extracted work memory.
- Neo4j stores relationship and project graph context.
- Chroma stores optional semantic-search indexes.
- Local model support remains the default; cloud providers are opt-in.

## Major Modules

- `backend/main.py`: API routes, onboarding, chat, sync, export, and intelligence surfaces.
- `backend/storage/`: Postgres adapter, Chroma integration, backup, and resilience checks.
- `backend/intelligence/`: project risk, meeting quality, CRM, workflow, and reporting modules.
- `backend/slack`, `backend/gmail`, `backend/fathom`, `backend/linear`, `backend/calendar`: source connectors.
- `app/SudoBrain`: native client views and local API client.
- `scripts/`: public-safety verification, demo data, smoke tests, and maintenance helpers.
