# Privacy and Data Safety

SudoBrain can read sensitive work communication. Run it only in environments
where you are allowed to process that data.

## What SudoBrain Reads

Depending on configuration, SudoBrain can read:

- Meeting recordings and transcripts.
- Slack channel messages and optional direct messages.
- Gmail messages and supported attachments.
- Local Git repository metadata and commit history.
- Linear issues.

## What Is Stored Locally

SudoBrain stores normalized source copies and extracted knowledge in Postgres.
It can also store relationship nodes and edges in Neo4j. Generated local data,
recordings, transcripts, vector stores, OAuth tokens, and database files should
remain untracked and private.

## Read-Only Source Policy

Normal sync paths are read-only for Slack, Gmail, Fathom, and repository
sources. They fetch data and write only to local SudoBrain storage. They should
not send messages, delete messages, archive email, label email, mutate meetings,
or modify repositories.

## Direct Messages

Slack direct-message ingestion is optional. When enabled, messages are stored
locally and classified before extraction.

Low-signal chat is ignored for knowledge extraction. Messages need stronger
signals such as project context, task/action wording, decisions, promises, or
file context before they can become extracted knowledge.

## Derived Knowledge

Actions, decisions, promises, people, and projects are generated from source
text. Extraction can be wrong. Review extracted knowledge before relying on it
for decisions, commitments, or reporting.

## Disable Integrations

Set these values to `false` in `.env`:

```bash
SUDOBRAIN_SYNC_GMAIL=false
SUDOBRAIN_SYNC_SLACK=false
SUDOBRAIN_SYNC_FATHOM=false
SUDOBRAIN_SYNC_PROJECT_CONTEXT=false
SUDOBRAIN_SLACK_INCLUDE_DMS=false
SUDOBRAIN_SLACK_EXTRACT_KNOWLEDGE=false
```

## Delete Local Data

Stop the backend first. Then remove the local data directory and any local
database volumes you configured. If you use Docker Compose, remove volumes only
when you are certain you no longer need the data:

```bash
docker compose down
docker volume ls
```

For manual databases, delete data using your normal Postgres and Neo4j
administration tools.

## Public Issues and Logs

Do not paste real messages, emails, transcripts, recordings, customer names,
OAuth tokens, API keys, or database dumps into public issues.
