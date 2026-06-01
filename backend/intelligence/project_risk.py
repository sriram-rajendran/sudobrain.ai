"""Project velocity + risk score.

Per Linear project:
- open_count / done_count / overdue_count
- close_rate_14d: fraction of issues that moved to done in the last 14 days
- backlog_age_days: median age of open issues
- overdue_ratio: overdue / open
- chatter_volume: slack messages mentioning project name in last 14d
- composite_risk: 0-100 weighted by above

Output: projects ranked by risk.
"""

from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection


def _normalize(value: float, low: float, high: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0
    return round((value - low) / (high - low) * 100, 1)


def compute_project_risk() -> dict:
    conn = get_connection()
    try:
        # Project list
        projects = conn.execute(
            "SELECT id, name FROM linear_projects"
        ).fetchall()

        result = []
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=14)

        for p in projects:
            pname = p["name"]
            # Aggregate issue stats for this project
            stats = conn.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE state_type NOT IN ('completed','cancelled')) AS open,
                    COUNT(*) FILTER (WHERE state_type = 'completed') AS done,
                    COUNT(*) FILTER (
                        WHERE state_type NOT IN ('completed','cancelled')
                          AND due_date IS NOT NULL AND due_date < CURRENT_DATE
                    ) AS overdue,
                    COUNT(*) FILTER (
                        WHERE state_type = 'completed' AND completed_at >= ?
                    ) AS closed_recent,
                    AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400)
                        FILTER (WHERE state_type NOT IN ('completed','cancelled')) AS avg_age_days
                FROM linear_issues
                WHERE project_name = ?
                """,
                (recent_cutoff, pname),
            ).fetchone()

            open_count = stats["open"] or 0
            done_count = stats["done"] or 0
            overdue = stats["overdue"] or 0
            closed_recent = stats["closed_recent"] or 0
            avg_age = float(stats["avg_age_days"] or 0)
            total = open_count + done_count

            if total == 0:
                continue

            close_rate_14d = closed_recent / total if total else 0
            overdue_ratio = overdue / open_count if open_count else 0

            # Slack chatter: messages with project name as substring in last 14d
            chatter = conn.execute(
                """
                SELECT COUNT(*) c FROM slack_messages
                WHERE LOWER(text) LIKE LOWER(?)
                  AND message_at >= ?
                """,
                (f"%{pname}%", recent_cutoff),
            ).fetchone()["c"] or 0

            # Composite risk: higher = more at risk
            risk_score = round(
                _normalize(overdue_ratio, 0.0, 0.5) * 0.30 +
                _normalize(avg_age, 30, 120) * 0.25 +
                _normalize(open_count, 5, 50) * 0.20 +
                (100 - _normalize(close_rate_14d, 0.0, 0.3)) * 0.15 +
                _normalize(chatter, 5, 40) * 0.10,
                1,
            )

            if risk_score >= 70:
                status = "critical"
            elif risk_score >= 50:
                status = "at_risk"
            elif risk_score >= 30:
                status = "watch"
            else:
                status = "healthy"

            result.append({
                "project": pname,
                "open_issues": open_count,
                "done_issues": done_count,
                "overdue": overdue,
                "overdue_ratio": round(overdue_ratio, 2),
                "closed_recent_14d": closed_recent,
                "close_rate_14d": round(close_rate_14d, 2),
                "avg_open_age_days": round(avg_age, 1),
                "chatter_14d": chatter,
                "risk_score": risk_score,
                "status": status,
            })
    finally:
        conn.close()

    result.sort(key=lambda p: -p["risk_score"])

    return {
        "total_projects": len(result),
        "critical": [p for p in result if p["status"] == "critical"],
        "at_risk": [p for p in result if p["status"] == "at_risk"],
        "all": result,
    }
