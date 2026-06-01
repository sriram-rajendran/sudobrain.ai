# Source Integrations

SudoBrain treats source integrations as read-only connectors that normalize
external context into `SourceDocument` records. The connector catalog is exposed
at `/sources/catalog` and mirrored in `/extensions` so the macOS app, web
companion, and plugin authors can see which sources are shipped, partial, or
planned.

## Current Contract

- `status=partial`: source has an existing local capture/sync surface or a
  related connector path, but may not cover every vendor API flow yet.
- `status=planned`: source has a stable catalog contract and privacy-control
  slot; the vendor API client is still to be implemented.
- `access=read_only`: third-party APIs must fetch only unless a separate
  approval-aware write action is added.
- `access=local_read_only`: reads local files or local app exports only.
- `access=local_capture`: accepts explicit user-submitted capture payloads.

Preview the catalog:

```bash
curl http://127.0.0.1:8420/sources/catalog
curl "http://127.0.0.1:8420/sources/catalog?category=engineering"
curl "http://127.0.0.1:8420/sources/catalog?status=planned"
```

Preview GitHub without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/github/preview \
  -H 'Content-Type: application/json' \
  -d '{"repo":"owner/repo","limit":10}'
```

Use `SUDOBRAIN_GITHUB_TOKEN` or the request `token` field for private repos,
discussion GraphQL access, or higher rate limits. Token values are never
returned from preview health output.

Preview Notion without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/notion/preview \
  -H 'Content-Type: application/json' \
  -d '{"limit":10}'
```

Use `SUDOBRAIN_NOTION_TOKEN` or the request `token` field. The connector uses
Notion search to normalize pages and databases into source documents.

Preview Google Drive without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/google-drive/preview \
  -H 'Content-Type: application/json' \
  -d '{"limit":10,"query":"trashed=false"}'
```

Use `SUDOBRAIN_GOOGLE_DRIVE_TOKEN` or the request `token` field. Google Docs,
Sheets, and Slides are exported as text-friendly previews; binary files are
listed as metadata-only source documents.

Preview Confluence without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/confluence/preview \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://example.atlassian.net","limit":10}'
```

Use `SUDOBRAIN_CONFLUENCE_BASE_URL` plus either
`SUDOBRAIN_CONFLUENCE_EMAIL`/`SUDOBRAIN_CONFLUENCE_TOKEN` or
`SUDOBRAIN_CONFLUENCE_BEARER_TOKEN`. Optional `SUDOBRAIN_CONFLUENCE_SPACE_ID`
limits previews to a single space.

Preview Jira without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/jira/preview \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://example.atlassian.net","jql":"ORDER BY updated DESC","limit":10}'
```

Use `SUDOBRAIN_JIRA_BASE_URL` plus either
`SUDOBRAIN_JIRA_EMAIL`/`SUDOBRAIN_JIRA_TOKEN` or
`SUDOBRAIN_JIRA_BEARER_TOKEN`. Optional `SUDOBRAIN_JIRA_JQL` scopes previews to
the projects, epics, sprints, blockers, or ownership slices you care about.

Preview Asana without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/asana/preview \
  -H 'Content-Type: application/json' \
  -d '{"workspace_gid":"workspace-id","limit":10}'
```

Use `SUDOBRAIN_ASANA_TOKEN` with optional `SUDOBRAIN_ASANA_WORKSPACE_GID` or
`SUDOBRAIN_ASANA_PROJECT_GID` to scope tasks, projects, assignees, due dates,
and section context.

Preview Trello without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/trello/preview \
  -H 'Content-Type: application/json' \
  -d '{"board_id":"board-id","limit":10}'
```

Use `SUDOBRAIN_TRELLO_API_KEY` and `SUDOBRAIN_TRELLO_TOKEN` with optional
`SUDOBRAIN_TRELLO_BOARD_ID` to scope boards, lists, cards, labels, members, and
comments.

Preview ClickUp without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/clickup/preview \
  -H 'Content-Type: application/json' \
  -d '{"list_id":"list-id","limit":10}'
```

Use `SUDOBRAIN_CLICKUP_TOKEN` with optional `SUDOBRAIN_CLICKUP_TEAM_ID` or
`SUDOBRAIN_CLICKUP_LIST_ID` to scope tasks, lists, spaces, assignees, tags, due
dates, and priority.

Preview Monday.com without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/monday/preview \
  -H 'Content-Type: application/json' \
  -d '{"board_ids":["board-id"],"limit":10}'
```

Use `SUDOBRAIN_MONDAY_TOKEN` with optional `SUDOBRAIN_MONDAY_BOARD_IDS` to
scope boards, items, updates, owners, assignment/status columns, and project
status fields.

Preview Microsoft Teams without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/microsoft-teams/preview \
  -H 'Content-Type: application/json' \
  -d '{"team_id":"team-id","channel_id":"channel-id","limit":10}'
```

Use `SUDOBRAIN_TEAMS_TOKEN` with optional `SUDOBRAIN_TEAMS_TEAM_ID`,
`SUDOBRAIN_TEAMS_CHANNEL_ID`, or `SUDOBRAIN_TEAMS_CHAT_ID` to preview channel
messages, chat messages, meeting metadata, attendees, links, and file
attachments through Microsoft Graph.

Preview Zoom without ingesting data:

```bash
curl -X POST http://127.0.0.1:8420/extensions/connectors/zoom/preview \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","from_date":"2026-01-01","to_date":"2026-01-31","limit":10}'
```

Use `SUDOBRAIN_ZOOM_TOKEN` with optional `SUDOBRAIN_ZOOM_USER_ID`,
`SUDOBRAIN_ZOOM_FROM`, and `SUDOBRAIN_ZOOM_TO` to scope cloud recording
previews. The connector normalizes meeting topics, hosts, share links,
recording files, transcript files, summary/action-item files, and participant
audio metadata. Set `include_file_text` or `SUDOBRAIN_ZOOM_INCLUDE_FILE_TEXT`
only when a preview should download small transcript/summary text files.

## Source Families

### Engineering

- GitHub: issues, PRs, reviews, discussions, releases, commits, CI failures.
- Terminal / Dev Activity: shell history, build failures, local logs, test runs.

### Knowledge Bases And Documents

- Notion: docs, meeting notes, project plans, decision logs, databases.
- Google Drive / Docs / Sheets / Slides: specs, planning docs, spreadsheets,
  decks.
- Confluence: internal docs, architecture pages, runbooks.
- Local Files / Folders: PDFs, Markdown, docs, notes, exported chats.

### Projects

- Jira: tickets, epics, sprint history, blockers, ownership.
- Asana, Trello, ClickUp, Monday.com: tasks, project status, assignments, board
  updates, and comments.

### Communication, Meetings, And Email

- Microsoft Teams: messages, meetings, files, call transcripts.
- Zoom and Google Meet: recordings, transcripts, summaries, action items.
- Calendar: metadata, attendees, recurring patterns, prep context.
- Outlook / Microsoft 365 Mail and IMAP: non-Gmail email sources.

### Customer And Operations

- CRM: HubSpot, Salesforce, Pipedrive.
- Support: Intercom, Zendesk, Freshdesk, Help Scout.
- Incidents: PagerDuty, Opsgenie, incident.io, Rootly.
- Observability: Datadog, Sentry, Grafana, PostHog, Amplitude.

### Design, Read-Later, And Capture

- Figma: comments, files, project links, design review threads.
- Raindrop, Pocket, browser history, and bookmarks.
- Voice notes and mobile capture for quick thoughts, decisions, and reminders.

## Implementation Order

The recommended implementation order is:

1. GitHub.
2. Notion and Google Drive.
3. Jira plus the existing Linear path.
4. Teams, Zoom, and Google Meet.
5. Outlook and IMAP.
6. CRM and support sources.
7. Incident and observability sources.
8. Figma, read-later tools, local dev activity, and voice/mobile capture polish.
