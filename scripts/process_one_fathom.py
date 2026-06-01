"""Process a single Fathom share URL through the full SudoBrain pipeline."""

import argparse
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

from backend.fathom.pipeline import run_fathom_pipeline


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("recording_id")
    parser.add_argument("share_url")
    args = parser.parse_args()

    result = run_fathom_pipeline(recording_id=args.recording_id, share_url=args.share_url)
    print("\n=== RESULT ===")
    print(json.dumps({k: v for k, v in result.items() if k != "knowledge"}, indent=2, default=str))
    k = result.get("knowledge") or {}
    print("\n=== ACTION ITEMS ===")
    for a in k.get("action_items", []):
        print(f"- [{a.get('assignee') or '?'}] {a.get('text')}  (due: {a.get('due_date') or '—'})")
    print("\n=== DECISIONS ===")
    for d in k.get("decisions", []):
        print(f"- {d.get('text')}  (by: {d.get('made_by') or '—'})")
    print("\n=== PROMISES ===")
    for p in k.get("promises", []):
        print(f"- {p.get('promised_by')} → {p.get('promised_to')}: {p.get('text')}  (due: {p.get('due_date') or '—'})")
