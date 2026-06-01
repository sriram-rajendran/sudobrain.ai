# Plugin And Extension Development

SudoBrain extensions should be small, auditable, and local-first by default.

## Interfaces

Contributor-facing protocols live in `backend/sdk/interfaces.py`:

- `Connector`: read-only source connector.
- `IntelligenceModule`: derives typed knowledge from source documents.
- `WorkflowAction`: dry-run and approval-aware workflow action.

The common data types are `SourceDocument`, `ExtractedItem`, and
`WorkflowActionResult`.

## Connector Rules

- Fetch source records read-only unless a write path is explicitly documented.
- Never return credentials or raw token values from `health()`.
- Preserve source identifiers so citations and provenance can link back to the
  original record.
- Keep connector-specific parsing outside the core API route layer.

## Sample Markdown Connector

`backend/connectors/local_markdown.py` shows the smallest useful connector:

```python
from backend.connectors.local_markdown import LocalMarkdownConnector

connector = LocalMarkdownConnector("./docs")
print(connector.health())
for document in connector.fetch(limit=10):
    print(document.title, document.external_id)
```

The built-in runtime exposes safe preview endpoints that do not ingest data or
execute external plugin code:

```bash
curl http://127.0.0.1:8420/extensions
curl -X POST http://127.0.0.1:8420/extensions/connectors/local-markdown/preview \
  -H 'Content-Type: application/json' \
  -d '{"root":"./docs","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/github/preview \
  -H 'Content-Type: application/json' \
  -d '{"repo":"owner/repo","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/notion/preview \
  -H 'Content-Type: application/json' \
  -d '{"limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/google-drive/preview \
  -H 'Content-Type: application/json' \
  -d '{"limit":5,"query":"trashed=false"}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/confluence/preview \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://example.atlassian.net","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/jira/preview \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://example.atlassian.net","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/asana/preview \
  -H 'Content-Type: application/json' \
  -d '{"workspace_gid":"workspace-id","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/trello/preview \
  -H 'Content-Type: application/json' \
  -d '{"board_id":"board-id","limit":5}'

curl -X POST http://127.0.0.1:8420/extensions/connectors/clickup/preview \
  -H 'Content-Type: application/json' \
  -d '{"list_id":"list-id","limit":5}'
```

Sample modules and actions can also be previewed without writes:

```bash
curl -X POST http://127.0.0.1:8420/extensions/intelligence/keyword-risk/preview \
  -H 'Content-Type: application/json' \
  -d '{"documents":[{"source":"demo","external_id":"1","title":"Plan","text":"Launch delay risk"}]}'

curl -X POST http://127.0.0.1:8420/extensions/actions/draft-notification/preview \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"title":"Review","body":"Check risk"}}'
```

## Workflow Action Rules

- Write-capable actions must support `dry_run=True`.
- Actions that send messages, update third-party systems, or mutate local data
  should set `requires_approval=True`.
- Results should be structured enough to show in execution history.

## Sample Intelligence Module And Action

- `backend/intelligence/sample_module.py` demonstrates an `IntelligenceModule`
  that emits risk signals from source documents.
- `backend/actions/sample_workflow_action.py` demonstrates an approval-aware
  workflow action that can be previewed before execution.
