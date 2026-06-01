#!/usr/bin/env python3
"""Static feature contract checks for public SudoBrain workflows.

These checks intentionally avoid private credentials and a live database. They
make sure the open-source app keeps exposing the key endpoint/UI contracts that
the desktop flows depend on.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require_text(path: str, needles: list[str]) -> None:
    text = (ROOT / path).read_text(errors="replace")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        print(f"{path} is missing expected feature contracts:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    require_text("backend/main.py", [
        '@app.get("/onboarding/status")',
        '@app.get("/config/status")',
        '@app.post("/config/save")',
        '@app.get("/review/queue")',
        '@app.patch("/action-items/{task_id}")',
        '@app.post("/action-items/{task_id}/complete")',
        '@app.patch("/promises/{promise_id}")',
        '@app.post("/promises/{promise_id}/{action}")',
        '@app.get("/recordings/{recording_id}/rich")',
        '@app.get("/graph/canvas")',
        '@app.post("/workflows/dry-run")',
        '@app.get("/workflows/templates")',
        '@app.get("/workflows/trace")',
        '@app.get("/workflows/approvals")',
        '@app.get("/workflows/graph")',
        '@app.get("/sync/export")',
        '@app.post("/sync/import")',
        '@app.get("/knowledge/provenance/{kind}/{item_id}")',
        '@app.get("/knowledge/trust-report")',
        '@app.get("/sources/catalog")',
        '@app.get("/sources/freshness")',
        '@app.get("/graph/export")',
        '@app.get("/graph/edge/explain")',
        '@app.get("/privacy/retention")',
        '@app.get("/privacy/sources")',
        '@app.post("/chat/feedback")',
        '@app.post("/chat/sessions")',
        '@app.get("/chat/sessions")',
        '@app.post("/capture/mobile")',
        '@app.post("/capture/channel/{channel_name}")',
        '@app.get("/documents/library")',
        '@app.get("/documents/watch-folders")',
        '@app.post("/bookmarks")',
        '@app.post("/webpage/summarize")',
        '@app.post("/ocr/extract")',
        '@app.get("/admin/dashboard")',
        '@app.get("/admin/audit-log")',
        '@app.get("/usage/analytics")',
        '@app.get("/observability/status")',
        '@app.get("/plugins")',
        '@app.post("/extensions/connectors/github/preview")',
        '@app.post("/extensions/connectors/notion/preview")',
        '@app.post("/extensions/connectors/google-drive/preview")',
        '@app.post("/extensions/connectors/confluence/preview")',
        '@app.post("/extensions/connectors/jira/preview")',
        '@app.post("/extensions/connectors/asana/preview")',
        '@app.post("/extensions/connectors/trello/preview")',
        '@app.post("/extensions/connectors/clickup/preview")',
        '@app.post("/extensions/connectors/monday/preview")',
        '@app.get("/mcp/client/status")',
        '@app.get("/mcp/client/tools")',
        '@app.post("/mcp/client/tools/preview")',
        '@app.get("/reports/{period}/export")',
        '@app.post("/reports/{period}/share")',
        '@app.get("/models/providers/health")',
        '@app.post("/models/providers/test")',
    ])
    require_text("app/SudoBrain/AppState.swift", [
        "case onboarding",
        "case review",
        "case promises",
        "case crossReferences",
        "case localSettings",
        "case admin",
    ])
    require_text("app/SudoBrain/Views/FunctionalViews.swift", [
        "struct OnboardingView",
        "struct KnowledgeReviewView",
        "struct PromisesView",
        "struct CrossReferencesView",
        "struct LocalSettingsView",
        "struct AdminDebugView",
        "/workflows/dry-run",
        "/sync/export",
    ])
    require_text("browser-extension/background.js", [
        "capture-page",
        "source_title",
        "chrome.storage.local",
    ])
    require_text("browser-extension/popup.html", [
        "Project tag",
        "Person tag",
        "Recent captures",
    ])
    require_text("Makefile", [
        "release-readiness",
        "scripts/release_readiness.py",
        "demo-gif",
        "scripts/generate_demo_gif.sh",
    ])
    require_text("backend/connectors/catalog.py", [
        'key="github"',
        'key="notion"',
        'key="google_drive"',
        'key="confluence"',
        'key="jira"',
        'key="asana"',
        'key="trello"',
        'key="clickup"',
        'key="monday"',
        'key="microsoft_teams"',
        'key="zoom"',
        'key="google_meet"',
        'key="outlook"',
        'key="imap"',
        'key="hubspot"',
        'key="salesforce"',
        'key="pipedrive"',
        'key="intercom"',
        'key="zendesk"',
        'key="freshdesk"',
        'key="help_scout"',
        'key="pagerduty"',
        'key="opsgenie"',
        'key="incident_io"',
        'key="rootly"',
        'key="datadog"',
        'key="sentry"',
        'key="grafana"',
        'key="posthog"',
        'key="amplitude"',
        'key="figma"',
        'key="raindrop"',
        'key="pocket"',
        'key="browser_history"',
        'key="local_files"',
        'key="terminal_activity"',
        'key="voice_notes"',
        'key="mobile_capture"',
    ])
    require_text("backend/connectors/github.py", [
        "class GitHubConnector",
        "pull_request_review",
        "ci_failure",
        "discussion",
        "preview_documents",
    ])
    require_text("backend/connectors/notion.py", [
        "class NotionConnector",
        "SUDOBRAIN_NOTION_TOKEN",
        "/search",
        "_plain_property_summary",
        "preview_documents",
    ])
    require_text("backend/connectors/google_drive.py", [
        "class GoogleDriveConnector",
        "SUDOBRAIN_GOOGLE_DRIVE_TOKEN",
        "EXPORT_MIME_TYPES",
        "/files",
        "preview_documents",
    ])
    require_text("backend/connectors/confluence.py", [
        "class ConfluenceConnector",
        "SUDOBRAIN_CONFLUENCE_BASE_URL",
        "/api/v2/pages",
        "_strip_html",
        "preview_documents",
    ])
    require_text("backend/connectors/jira.py", [
        "class JiraConnector",
        "SUDOBRAIN_JIRA_BASE_URL",
        "/rest/api/3/search",
        "_adf_to_text",
        "preview_documents",
    ])
    require_text("backend/connectors/asana.py", [
        "class AsanaConnector",
        "SUDOBRAIN_ASANA_TOKEN",
        "/tasks",
        "assignee",
        "preview_documents",
    ])
    require_text("backend/connectors/trello.py", [
        "class TrelloConnector",
        "SUDOBRAIN_TRELLO_API_KEY",
        "/boards/",
        "commentCard",
        "preview_documents",
    ])
    require_text("backend/connectors/clickup.py", [
        "class ClickUpConnector",
        "SUDOBRAIN_CLICKUP_TOKEN",
        "/task",
        "assignees",
        "preview_documents",
    ])
    require_text("backend/connectors/monday.py", [
        "class MondayConnector",
        "SUDOBRAIN_MONDAY_TOKEN",
        "items_page",
        "column_values",
        "preview_documents",
    ])
    print("Feature contract checks passed.")


if __name__ == "__main__":
    main()
