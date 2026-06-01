#!/usr/bin/env python3
"""Non-destructive release readiness audit for open-source launch prep."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "VERSION",
    "docs/release-checklist.md",
    "docs/release-manifest.json",
    "docs/release-notes-template.md",
    "docs/screenshots.md",
    ".github/workflows/verify.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/release.yml",
    "scripts/package_release.sh",
]

SCREENSHOTS = [
    "docs/assets/screenshots/today.svg",
    "docs/assets/screenshots/chat.svg",
    "docs/assets/screenshots/graph.svg",
    "docs/assets/screenshots/workflows.svg",
    "docs/assets/screenshots/admin.svg",
]


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def main() -> int:
    required = [{"path": path, "ok": exists(path)} for path in REQUIRED_FILES]
    screenshots = [{"path": path, "ok": exists(path)} for path in SCREENSHOTS]

    manifest_path = ROOT / "docs/release-manifest.json"
    manifest = {}
    manifest_ok = False
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest_ok = bool(manifest.get("version") and manifest.get("artifacts"))
        except Exception as exc:
            manifest = {"error": str(exc)}

    signing_ready = all(os.getenv(name) for name in ["APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD"])
    external_blockers = []
    if not signing_ready:
        external_blockers.append("Apple signing/notarization secrets are not configured.")
    external_blockers.append("GitHub Pages and Discussions require repository settings outside the worktree.")
    external_blockers.append("Captured GIFs require running and recording the app with demo data.")

    report = {
        "status": "ready_with_external_blockers" if all(item["ok"] for item in required + screenshots) and manifest_ok else "missing_repo_artifacts",
        "required_files": required,
        "screenshots": screenshots,
        "manifest": {"ok": manifest_ok, "value": manifest},
        "unsigned_package": {"script": "scripts/package_release.sh", "available": exists("scripts/package_release.sh")},
        "signing": {"apple_credentials_configured": signing_ready},
        "external_blockers": external_blockers,
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready_with_external_blockers" else 1


if __name__ == "__main__":
    raise SystemExit(main())
