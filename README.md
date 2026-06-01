# SudoBrain

SudoBrain is a local-first work knowledge engine. It reads work context from
meetings, recordings, Slack, Gmail, and local repositories, then builds an
auditable knowledge base of actions, decisions, promises, people, projects, and
relationships.

The project is designed for private/local deployment first: external sources are
read-only, raw data stays on your machine or infrastructure, and extracted
knowledge can be audited before it is used for decisions.

## Features

- Meeting and recording ingestion with transcript processing.
- Read-only Slack sync, including optional direct-message filtering.
- Read-only Gmail sync with attachment text extraction.
- Optional local repository context from Git history and README files.
- Structured extraction of actions, decisions, promises, people, and projects.
- Postgres storage plus optional Neo4j relationship graph.
- Source audit endpoints for validation, dedupe, and graph consistency checks.
- macOS SwiftUI app and browser-extension surfaces for local workflows.

## Architecture

- `backend/`: FastAPI service, source sync, extraction, storage, graph, and audit logic.
- `app/`: macOS SwiftUI client.
- `browser-extension/`: lightweight capture extension.
- `mockups/`: design prototypes.
- `scripts/`: optional local maintenance helpers.

Storage is local by default:

- Postgres stores source copies and extracted knowledge.
- Neo4j stores the relationship graph.
- Optional vector storage can be used for semantic search.
- Recordings, transcripts, OAuth tokens, and generated data are ignored by Git.

## Supported Sources

- Fathom and local recordings
- Slack channels and optional DMs
- Gmail messages and supported attachments
- Local Git repositories
- Linear issues, when configured

All external integrations are read-only in normal sync paths.

## Quick Start

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
docker compose up -d postgres neo4j
uvicorn backend.main:app --reload
```

Then check:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/graph/status
curl http://127.0.0.1:8000/sync/audit
```

The default `.env.example` disables external sync. Enable only the integrations
you want after reading [docs/privacy.md](docs/privacy.md).

## macOS App

The SwiftUI app lives in `app/`. A local backend should be running before using
the app:

```bash
cd app
swift build
```

For Xcode workflows, open or generate the project according to the files in
`app/`.

## Configuration

Important environment variables:

- `SUDOBRAIN_DATA_DIR`: local generated data directory.
- `SUDOBRAIN_LLM_COMMAND`: optional local reasoning CLI command.
- `POSTGRES_*`: Postgres connection.
- `NEO4J_*`: Neo4j connection.
- `SUDOBRAIN_SYNC_SLACK`, `SUDOBRAIN_SYNC_GMAIL`, `SUDOBRAIN_SYNC_FATHOM`: source toggles.
- `SUDOBRAIN_SLACK_INCLUDE_DMS`: include Slack direct-message scopes.
- `SUDOBRAIN_PROJECTS_ROOT`: folder of local Git repositories to scan.
- `SUDOBRAIN_PROJECT_ALIASES_JSON`: configurable project aliases.
- `SUDOBRAIN_PERSON_ALIASES_JSON`: configurable person aliases.
- `SELF_EMAIL`: optional email used for personal analytics.

See [docs/setup.md](docs/setup.md) for full setup and safe config examples.

## Source Audit

`/sync/audit` checks local storage and graph health without calling external
services. It reports validation status, duplicates, ignored scopes, graph
availability, stale graph nodes, and semantic quality issues.

## Verification

Run the same public-safety and build checks used by CI:

```bash
make verify
```

This checks for secrets, sensitive tracked files, private sample text,
read-only integration boundaries, whitespace issues, Python compile health, and
the macOS Swift build.

## Privacy Status

SudoBrain can process sensitive communication data. Keep it private until you
understand the storage model, retention behavior, and sync toggles. See
[docs/privacy.md](docs/privacy.md).

## Maturity

This project is early and intended for technically comfortable users. Expect
active changes around setup, extraction quality, UI, and review workflows.

## License

MIT. See [LICENSE](LICENSE).
