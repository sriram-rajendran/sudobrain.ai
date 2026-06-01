# Contributing

Thanks for helping improve SudoBrain.

## Development Principles

- Keep external integrations read-only unless a feature explicitly documents and
  gates a write path.
- Do not commit private source data, OAuth files, recordings, transcripts,
  database files, generated vector stores, or local environment files.
- Prefer configurable project/person aliases over hardcoded company-specific
  assumptions.
- Include validation or audit evidence for changes that affect ingestion,
  extraction, dedupe, or graph behavior.

## Local Setup

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
docker compose up -d postgres neo4j
uvicorn backend.main:app --reload
```

## Checks Before a Pull Request

```bash
git diff --check
python -m compileall -q backend
curl http://127.0.0.1:8000/sync/audit
```

If local services are not available, say which checks were skipped and why.

## Pull Request Notes

Please include:

- What changed.
- Which source or storage path is affected.
- How privacy/read-only behavior is preserved.
- Commands run and results.
- Any migration or configuration notes.
