#!/usr/bin/env python3
"""Public-repo safety and build verification for SudoBrain."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, cwd: Path = ROOT, required: bool = True) -> int:
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, text=True)
    if required and result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def capture(cmd: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout


def tracked_files() -> list[str]:
    return [line for line in capture(["git", "ls-files"]).splitlines() if line]


def untracked_files() -> list[str]:
    return [line for line in capture(["git", "ls-files", "-o", "--exclude-standard"]).splitlines() if line]


SENSITIVE_FILE_RE = re.compile(
    r"(^|/)(\.env($|\.)|credentials\.json$|token\.json$|gcal_token\.json$|"
    r".*\.(pem|key|p12|p8|db|sqlite|sqlite3|sql|dump|wav|mp3|m4a|mp4|mov|pyc)$)",
    re.IGNORECASE,
)

ALLOWED_SENSITIVE_FILES = {".env.example"}


def check_sensitive_files() -> None:
    problems = [
        path for path in tracked_files()
        if SENSITIVE_FILE_RE.search(path) and path not in ALLOWED_SENSITIVE_FILES
    ]
    if problems:
        print("Tracked sensitive/generated files found:", file=sys.stderr)
        for path in problems:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    ignored_or_untracked = [
        path for path in untracked_files()
        if SENSITIVE_FILE_RE.search(path) and path not in ALLOWED_SENSITIVE_FILES
    ]
    if ignored_or_untracked:
        print("Untracked sensitive/generated files are visible to Git:", file=sys.stderr)
        for path in ignored_or_untracked:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    print("Sensitive-file check passed.")


PRIVATE_PATTERNS = [
    "sri" + "ram",
    "data" + "flo",
    "co" + "dex",
    "/" + "Users/",
    "github.com-" + "personal",
    "Rah" + "ul",
    "Pri" + "ya",
    "Mac" + "Book Pro",
    "Gmail " + "MCP",
    "send " + "Slack",
    "sends " + "Slack",
    "JWT refresh " + "token",
]


SKIP_CONTENT_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns"}
SKIP_CONTENT_DIRS = {".git", ".build", "build", "dist", "DerivedData", "__pycache__"}


def iter_scanned_files() -> list[Path]:
    paths: list[Path] = []
    candidates = list(dict.fromkeys([*tracked_files(), *untracked_files()]))
    for rel in candidates:
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in SKIP_CONTENT_SUFFIXES:
            continue
        if any(part in SKIP_CONTENT_DIRS for part in path.relative_to(ROOT).parts):
            continue
        paths.append(path)
    return paths


def check_private_text() -> None:
    findings: list[tuple[str, int, str]] = []
    lowered = [(pattern, pattern.lower()) for pattern in PRIVATE_PATTERNS]
    for path in iter_scanned_files():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower_line = line.lower()
            for pattern, lower_pattern in lowered:
                if lower_pattern in lower_line:
                    findings.append((str(path.relative_to(ROOT)), line_no, pattern))
    if findings:
        print("Private/public-facing text scan found blocked terms:", file=sys.stderr)
        for file_name, line_no, pattern in findings[:50]:
            print(f"  {file_name}:{line_no}: {pattern}", file=sys.stderr)
        if len(findings) > 50:
            print(f"  ... {len(findings) - 50} more", file=sys.stderr)
        sys.exit(1)
    print("Private/public-facing text scan passed.")


MUTATING_INTEGRATION_RE = re.compile(
    r"(chat_postMessage|files_upload|reactions_add|conversations_(archive|rename|set)|"
    r"users\(\)\.messages\(\)\.(send|delete|modify|trash)|"
    r"\b(send_email|post_slack|create_calendar_event|send_message)\b)",
    re.IGNORECASE,
)


READ_ONLY_ALLOWLIST = {
    "backend/intelligence/workflows.py",
    "scripts/verify_public_repo.py",
}


def check_read_only_policy() -> None:
    findings: list[tuple[str, int, str]] = []
    for path in iter_scanned_files():
        rel = str(path.relative_to(ROOT))
        if rel in READ_ONLY_ALLOWLIST:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if MUTATING_INTEGRATION_RE.search(line):
                findings.append((rel, line_no, line.strip()))
    if findings:
        print("Possible mutating external-integration code found:", file=sys.stderr)
        for rel, line_no, line in findings:
            print(f"  {rel}:{line_no}: {line}", file=sys.stderr)
        sys.exit(1)
    print("Read-only integration policy check passed.")


def check_gitleaks() -> None:
    if not shutil.which("gitleaks"):
        if os.getenv("SUDOBRAIN_ALLOW_MISSING_GITLEAKS") == "1":
            print("gitleaks not installed; skipping because SUDOBRAIN_ALLOW_MISSING_GITLEAKS=1.")
            return
        print("gitleaks is required. Install it or set SUDOBRAIN_ALLOW_MISSING_GITLEAKS=1 for local-only skips.", file=sys.stderr)
        sys.exit(1)
    run(["gitleaks", "detect", "--source", ".", "--redact", "--verbose"])
    run(["gitleaks", "detect", "--source", ".", "--no-git", "--redact", "--verbose"])


def clean_generated() -> None:
    shutil.rmtree(ROOT / "app" / ".build", ignore_errors=True)
    for cache_dir in [ROOT / "backend" / "__pycache__", *ROOT.glob("backend/**/__pycache__"), ROOT / "scripts" / "__pycache__"]:
        shutil.rmtree(cache_dir, ignore_errors=True)


def main() -> None:
    os.chdir(ROOT)
    clean_generated()
    check_sensitive_files()
    check_private_text()
    check_read_only_policy()
    check_gitleaks()
    run(["git", "diff", "--check"])
    run([sys.executable, "-m", "compileall", "-q", "backend", "scripts"])
    clean_generated()
    if (ROOT / "app" / "Package.swift").exists():
        run(["swift", "build"], cwd=ROOT / "app")
    print("\nPublic repo verification passed.")


if __name__ == "__main__":
    main()
