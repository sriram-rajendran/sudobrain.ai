"""Baseline anomaly detection.

Computes daily stats for the last N days and flags any day/metric that is
>2σ away from its rolling baseline.

Metrics tracked per day:
- total_slack_messages (all users)
- your_slack_messages
- new_linear_issues (created)
- closed_linear_issues (completed_at)
- gmail_received
- decisions_made (extracted)
- promises_made (extracted)
"""

import os
import statistics
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()


def _daily_counts(days: int) -> list[dict]:
    conn = get_connection()
    try:
        # Use IST-aligned dates
        rows = conn.execute(
            """
            WITH day_series AS (
                SELECT generate_series(
                    CURRENT_DATE - (? || ' days')::interval,
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS d
            )
            SELECT
                day_series.d AS day,
                (SELECT COUNT(*) FROM slack_messages
                    WHERE DATE(message_at AT TIME ZONE 'Asia/Kolkata') = day_series.d) AS slack_total,
                (SELECT COUNT(*) FROM linear_issues
                    WHERE DATE(created_at) = day_series.d) AS linear_new,
                (SELECT COUNT(*) FROM linear_issues
                    WHERE DATE(completed_at) = day_series.d) AS linear_closed,
                (SELECT COUNT(*) FROM gmail_messages
                    WHERE DATE(date) = day_series.d) AS gmail
            FROM day_series
            ORDER BY day_series.d
            """,
            (days,),
        ).fetchall()

        # Also per-user stats for self
        self_uid = conn.execute(
            "SELECT su.id FROM slack_users su JOIN people p ON p.id = su.person_id "
            "WHERE LOWER(p.email) = ? LIMIT 1",
            (SELF_EMAIL,),
        ).fetchone()
        self_slack_id = self_uid["id"] if self_uid else None

        self_daily = {}
        if self_slack_id:
            self_rows = conn.execute(
                """
                SELECT DATE(message_at AT TIME ZONE 'Asia/Kolkata') AS day,
                       COUNT(*) AS c
                FROM slack_messages
                WHERE user_id = ? AND message_at >= CURRENT_DATE - (? || ' days')::interval
                GROUP BY day
                """,
                (self_slack_id, days),
            ).fetchall()
            self_daily = {r["day"]: r["c"] for r in self_rows}

    finally:
        conn.close()

    return [
        {
            "date": r["day"].isoformat(),
            "slack_total": r["slack_total"] or 0,
            "self_slack": self_daily.get(r["day"], 0),
            "linear_new": r["linear_new"] or 0,
            "linear_closed": r["linear_closed"] or 0,
            "gmail": r["gmail"] or 0,
        }
        for r in rows
    ]


def _flag_outliers(daily: list[dict], metric: str, sigma: float = 2.0) -> list[dict]:
    """Return days where metric > baseline_mean + sigma×std."""
    values = [d[metric] for d in daily]
    if len(values) < 7:
        return []
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) or 1e-6
    anomalies = []
    for d in daily:
        v = d[metric]
        z = (v - mean) / stdev
        if abs(z) >= sigma and v > 0:
            anomalies.append({
                "date": d["date"],
                "metric": metric,
                "value": v,
                "baseline_mean": round(mean, 1),
                "z_score": round(z, 2),
                "direction": "high" if z > 0 else "low",
            })
    return anomalies


def compute_anomalies(days: int = 30, sigma: float = 2.0) -> dict:
    daily = _daily_counts(days)
    if len(daily) < 7:
        return {"error": "insufficient history"}

    metrics = ["slack_total", "self_slack", "linear_new", "linear_closed", "gmail"]
    all_anomalies = []
    for m in metrics:
        all_anomalies.extend(_flag_outliers(daily, m, sigma=sigma))
    all_anomalies.sort(key=lambda a: (-abs(a["z_score"]), a["date"]))

    return {
        "period_days": days,
        "sigma_threshold": sigma,
        "total_anomalies": len(all_anomalies),
        "anomalies": all_anomalies[:25],
        "daily": daily,
    }
