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
./scripts/bootstrap_local.sh
./run_backend.sh
```

Load public-safe demo data in another terminal:

```bash
make demo
```

## Checks Before a Pull Request

```bash
make verify
make smoke
```

If local services are available, also include `/sync/audit` results. If any
check is skipped, say which check was skipped and why.

## Contributor-Friendly Areas

- Demo data and fixture coverage.
- Source citation cards and provenance UI.
- Markdown/JSON export improvements.
- Connector SDK examples.
- Docs, screenshots, and release checklist maintenance.

## Pull Request Notes

Please include:

- What changed.
- Which source or storage path is affected.
- How privacy/read-only behavior is preserved.
- Commands run and results.
- Any migration or configuration notes.
