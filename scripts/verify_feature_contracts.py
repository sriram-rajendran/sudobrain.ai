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
        '@app.get("/mcp/client/status")',
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
    print("Feature contract checks passed.")


if __name__ == "__main__":
    main()
