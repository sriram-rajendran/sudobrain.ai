# Data Flow

```mermaid
flowchart TD
  capture["Capture or read-only sync"] --> source["Raw source record"]
  source --> storage["Postgres source tables"]
  storage --> extract["Structured extraction"]
  extract --> review["Review queue and audit"]
  extract --> memory["Actions, decisions, promises, people, projects"]
  memory --> graph["Neo4j graph"]
  memory --> vectors["Chroma vectors"]
  graph --> chat["Chat and intelligence"]
  vectors --> chat
  memory --> export["JSON and Markdown export"]
```

## Source Records

Meetings, Slack messages, Gmail messages, Fathom meetings, Linear issues,
Calendar events, and local repository context are stored before derived facts are
used. This gives SudoBrain an audit trail for later review.

## Extracted Knowledge

The core work-memory objects are:

- Action items
- Decisions
- Promises
- People
- Projects
- Transcript segments
- Review and contradiction records

## Trust Surfaces

- `/sync/audit` checks source and graph health without external network calls.
- `/knowledge/export?format=json` exports structured tables for portability.
- `/knowledge/export?format=markdown` exports reviewable knowledge artifacts.
- Chat source metadata links answers back to local source rows when available.
