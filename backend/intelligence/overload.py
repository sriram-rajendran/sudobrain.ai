"""Overload score — composite measure of how overloaded the user is.

Factors:
- urgent_open:          open Linear issues assigned to you with urgent/high priority
- overdue_tasks:        action_items + linear_issues past due
- promise_backlog:      pending promises assigned BY you
- weekend_slack_ratio:  fraction of your slack messages sent on weekends (last 30d)
- avg_response_latency: median hours between your slack messages in threads you reply in
- fulfillment_rate:     rolling % of your promises marked delivered

Each factor is normalized to 0-100 via thresholds, then weight-averaged.
Returns the composite score + the top contributing factors.
"""

import os
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()


def _self_person() -> dict | None:
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT id, name, email FROM people WHERE LOWER(email) = ? OR is_self = TRUE LIMIT 1",
            (SELF_EMAIL,),
        ).fetchone()
        return dict(r._row) if r else None
    finally:
        conn.close()


def _urgent_open(email: str) -> int:
    conn = get_connection()
    try:
        r = conn.execute(
            """
            SELECT COUNT(*) c FROM linear_issues
            WHERE LOWER(assignee_email) = ?
              AND state_type NOT IN ('completed','cancelled')
              AND priority BETWEEN 1 AND 2
            """,
            (email,),
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def _overdue_count(email: str, name: str) -> int:
    conn = get_connection()
    try:
        lin = conn.execute(
            """
            SELECT COUNT(*) c FROM linear_issues
            WHERE LOWER(assignee_email) = ?
              AND state_type NOT IN ('completed','cancelled')
              AND due_date IS NOT NULL AND due_date < CURRENT_DATE
            """,
            (email,),
        ).fetchone()["c"]
        acts = conn.execute(
            """
            SELECT COUNT(*) c FROM action_items
            WHERE (LOWER(assignee) = ? OR assignee = ?)
              AND status = 'pending'
              AND due_date IS NOT NULL AND due_date < CURRENT_DATE
            """,
            (email, name),
        ).fetchone()["c"]
        return lin + acts
    finally:
        conn.close()


def _promise_backlog(name: str) -> int:
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT COUNT(*) c FROM promises "
            "WHERE promised_by_name = ? AND status = 'pending'",
            (name,),
        ).fetchone()
        return r["c"] if r else 0
    finally:
        conn.close()


def _fulfillment_rate(name: str) -> tuple[float, int]:
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE status = 'fulfilled') fulfilled, "
            "COUNT(*) total FROM promises WHERE promised_by_name = ?",
            (name,),
        ).fetchone()
        total = r["total"]
        if total == 0:
            return 1.0, 0  # no data → assume 100%
        return r["fulfilled"] / total, total
    finally:
        conn.close()


def _weekend_slack_ratio(slack_user_id: str, days: int = 30) -> tuple[float, int]:
    if not slack_user_id:
        return 0.0, 0
    conn = get_connection()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        r = conn.execute(
            "SELECT COUNT(*) total, "
            "COUNT(*) FILTER (WHERE EXTRACT(DOW FROM message_at AT TIME ZONE 'Asia/Kolkata') IN (0,6)) weekend "
            "FROM slack_messages WHERE user_id = ? AND message_at >= ?",
            (slack_user_id, since),
        ).fetchone()
        total = r["total"]
        if total == 0:
            return 0.0, 0
        return r["weekend"] / total, total
    finally:
        conn.close()


def _slack_user_id_for(person_id: int) -> str | None:
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT id FROM slack_users WHERE person_id = ? LIMIT 1",
            (person_id,),
        ).fetchone()
        return r["id"] if r else None
    finally:
        conn.close()


def _normalize(value: float, low: float, high: float) -> float:
    """Map value in [low, high] to 0-100. Clamps."""
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0
    return round((value - low) / (high - low) * 100, 1)


def compute_overload() -> dict:
    """Compute composite overload score for the user."""
    self = _self_person()
    if not self:
        return {"error": "no self person found", "score": 0}

    email = (self.get("email") or SELF_EMAIL).lower()
    name = self.get("name") or SELF_EMAIL
    slack_uid = _slack_user_id_for(self["id"])

    urgent = _urgent_open(email)
    overdue = _overdue_count(email, name)
    backlog = _promise_backlog(name)
    weekend_ratio, slack_total = _weekend_slack_ratio(slack_uid)
    fulfillment, prom_sample = _fulfillment_rate(name)

    # Score each factor 0-100 with conservative personal-workload thresholds.
    factors = {
        "urgent_open": {
            "value": urgent,
            "score": _normalize(urgent, 0, 25),
            "weight": 0.30,
            "description": f"{urgent} urgent Linear issues still open",
        },
        "overdue": {
            "value": overdue,
            "score": _normalize(overdue, 0, 15),
            "weight": 0.25,
            "description": f"{overdue} overdue tasks (Linear + extracted)",
        },
        "promise_backlog": {
            "value": backlog,
            "score": _normalize(backlog, 0, 20),
            "weight": 0.20,
            "description": f"{backlog} pending promises you owe",
        },
        "weekend_work": {
            "value": round(weekend_ratio, 3),
            "score": _normalize(weekend_ratio, 0.0, 0.30),
            "weight": 0.15,
            "description": (
                f"{round(weekend_ratio*100)}% of your slack last 30d was on weekends"
                f" ({slack_total} msgs)"
            ),
        },
        "low_fulfillment": {
            "value": round(fulfillment, 3),
            "score": _normalize(1.0 - fulfillment, 0.0, 0.70),
            "weight": 0.10,
            "description": (
                f"{round(fulfillment*100)}% promise fulfillment rate"
                f" (sample: {prom_sample})"
                if prom_sample > 0
                else "no promise history yet"
            ),
        },
    }

    composite = round(
        sum(f["score"] * f["weight"] for f in factors.values()), 1
    )

    ranked = sorted(
        factors.items(), key=lambda kv: kv[1]["score"] * kv[1]["weight"], reverse=True
    )
    top_contributors = [
        {"factor": k, **v} for k, v in ranked if v["score"] > 0
    ]

    if composite >= 75:
        verdict = "severely overloaded"
    elif composite >= 55:
        verdict = "overloaded"
    elif composite >= 35:
        verdict = "busy"
    elif composite >= 15:
        verdict = "moderate"
    else:
        verdict = "light"

    return {
        "score": composite,
        "verdict": verdict,
        "person": {"id": self["id"], "name": name, "email": email},
        "top_contributors": top_contributors[:3],
        "factors": factors,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
