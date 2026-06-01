#!/usr/bin/env python3
"""Smoke test a local SudoBrain backend.

This intentionally avoids calling external integrations. It verifies that the
API is reachable and that the public demo/readiness surfaces return parseable
JSON with the expected shape.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


CHECKS = [
    ("health", "/health", ("status",)),
    ("onboarding", "/onboarding/status", ("checks", "complete")),
    ("sync status", "/sync/status", ("slack", "gmail", "linear")),
    ("source audit", "/sync/audit", ()),
    ("knowledge export", "/knowledge/export?format=json", ("tables", "exported_at")),
]


def fetch_json(base_url: str, path: str, timeout: float) -> dict:
    with urlopen(f"{base_url}{path}", timeout=timeout) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def wait_for_backend(base_url: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            payload = fetch_json(base_url, "/health", timeout=2)
            if payload.get("status") == "ok":
                return True
        except (OSError, URLError, json.JSONDecodeError):
            time.sleep(1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local startup smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8420")
    parser.add_argument("--wait", type=float, default=20)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()

    if not wait_for_backend(args.base_url, args.wait):
        print(f"FAIL backend did not become healthy at {args.base_url}", file=sys.stderr)
        return 1

    failures = []
    for name, path, required_keys in CHECKS:
        try:
            payload = fetch_json(args.base_url, path, timeout=args.timeout)
            missing = [key for key in required_keys if key not in payload]
            if missing:
                failures.append(f"{name}: missing keys {', '.join(missing)}")
            else:
                print(f"PASS {name}")
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("SudoBrain startup smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
