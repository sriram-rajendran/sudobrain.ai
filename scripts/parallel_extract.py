"""Parallel local knowledge extraction across Linear / Gmail / Slack."""

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
logger = logging.getLogger("parallel_extract")

from backend.storage.database import get_connection

WORKERS = 4


def _q(conn, sql, *args) -> int:
    return conn.execute(sql, args).fetchone()["c"]


def progress_snapshot() -> dict:
    c = get_connection()
    try:
        return {
            "linear": _q(c, "SELECT COUNT(*) c FROM linear_issues WHERE extracted=TRUE"),
            "linear_total": _q(c, "SELECT COUNT(*) c FROM linear_issues"),
            "gmail": _q(c, "SELECT COUNT(*) c FROM gmail_messages WHERE extracted=TRUE"),
            "gmail_total": _q(c, "SELECT COUNT(*) c FROM gmail_messages"),
            "slack": _q(c, "SELECT COUNT(*) c FROM slack_messages WHERE extracted=TRUE"),
            "slack_total": _q(c, "SELECT COUNT(*) c FROM slack_messages"),
            "action_items": _q(c, "SELECT COUNT(*) c FROM action_items"),
            "decisions": _q(c, "SELECT COUNT(*) c FROM decisions"),
            "promises": _q(c, "SELECT COUNT(*) c FROM promises"),
        }
    finally:
        c.close()


def run_linear() -> tuple[str, int]:
    from backend.linear.ingest import extract_from_issues
    t = time.time()
    n = extract_from_issues(batch_size=30)
    return f"linear", n, time.time() - t


def run_gmail() -> tuple[str, int]:
    from backend.gmail.ingest import extract_from_emails
    t = time.time()
    n = extract_from_emails(limit=200)
    return f"gmail", n, time.time() - t


def run_slack_channel(channel_id: str, channel_name: str):
    from backend.slack.ingest import extract_from_messages
    t = time.time()
    try:
        n = extract_from_messages(channel_id)
    except Exception as e:
        return channel_name, 0, time.time() - t, str(e)
    return channel_name, n, time.time() - t, None


def main():
    print(f"=== parallel extraction, {WORKERS} workers ===", flush=True)
    snap0 = progress_snapshot()
    print(f"start: {snap0}", flush=True)

    # Collect all units of work
    c = get_connection()
    try:
        chans = c.execute(
            "SELECT id, name FROM slack_channels "
            "WHERE sync_enabled=TRUE AND is_archived=FALSE"
        ).fetchall()
        slack_units = [(r["id"], r["name"]) for r in chans]
    finally:
        c.close()

    print(f"units: 1 linear + 1 gmail + {len(slack_units)} slack channels", flush=True)

    futures = {}
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # Submit linear + gmail + all slack channels
        futures[pool.submit(run_linear)] = "linear"
        futures[pool.submit(run_gmail)] = "gmail"
        for cid, name in slack_units:
            futures[pool.submit(run_slack_channel, cid, name)] = f"slack:{name}"

        done = 0
        total = len(futures)
        for fut in as_completed(futures):
            done += 1
            label = futures[fut]
            try:
                result = fut.result()
                if len(result) == 3:  # linear/gmail
                    name, n, elapsed = result
                    print(f"  [{done}/{total}] {name} done: {n} extracted ({elapsed:.0f}s)", flush=True)
                else:  # slack
                    name, n, elapsed, err = result
                    if err:
                        print(f"  [{done}/{total}] slack:{name} FAIL: {err[:80]} ({elapsed:.0f}s)", flush=True)
                    elif n > 0:
                        print(f"  [{done}/{total}] slack:{name}: {n} ({elapsed:.0f}s)", flush=True)
            except Exception as e:
                print(f"  [{done}/{total}] {label} EXCEPTION: {e}", flush=True)

            # Progress snapshot every 10 completions
            if done % 10 == 0:
                snap = progress_snapshot()
                print(f"    progress: ai={snap['action_items']} dec={snap['decisions']} prom={snap['promises']}", flush=True)

    elapsed = time.time() - t_start
    snap_end = progress_snapshot()
    print(f"\n=== done in {elapsed:.0f}s ({elapsed/60:.1f} min) ===", flush=True)
    print(f"end: {snap_end}", flush=True)
    print(f"\ndelta:")
    print(f"  linear extracted: {snap_end['linear']}/{snap_end['linear_total']} (+{snap_end['linear']-snap0['linear']})")
    print(f"  gmail extracted : {snap_end['gmail']}/{snap_end['gmail_total']} (+{snap_end['gmail']-snap0['gmail']})")
    print(f"  slack extracted : {snap_end['slack']}/{snap_end['slack_total']} (+{snap_end['slack']-snap0['slack']})")
    print(f"  action_items    : {snap_end['action_items']} (+{snap_end['action_items']-snap0['action_items']})")
    print(f"  decisions       : {snap_end['decisions']} (+{snap_end['decisions']-snap0['decisions']})")
    print(f"  promises        : {snap_end['promises']} (+{snap_end['promises']-snap0['promises']})")


if __name__ == "__main__":
    main()
