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
