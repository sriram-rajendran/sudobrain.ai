"""Sample approval-aware workflow action."""

from __future__ import annotations

from backend.sdk import WorkflowActionResult


class DraftNotificationAction:
    name = "draft_notification"
    requires_approval = True

    def run(self, payload: dict, dry_run: bool = True) -> WorkflowActionResult:
        title = payload.get("title", "SudoBrain notification")
        body = payload.get("body", "")
        return WorkflowActionResult(
            status="preview" if dry_run else "queued",
            message=f"{title}: {body}",
            data={"title": title, "body": body},
            requires_approval=True,
        )
