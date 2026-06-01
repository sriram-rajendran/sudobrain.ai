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

## Workflow Action Rules

- Write-capable actions must support `dry_run=True`.
- Actions that send messages, update third-party systems, or mutate local data
  should set `requires_approval=True`.
- Results should be structured enough to show in execution history.
