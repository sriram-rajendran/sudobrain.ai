"""Trust map — per-person promise fulfillment rate.

For each person who has been seen promising things, compute:
  - total_promises
  - fulfilled
  - pending
  - overdue
  - fulfillment_rate (fulfilled / (fulfilled + expired))
  - pending_value (sum of unresolved promises, weighted by age)

Ranks people by trust (fulfillment rate) with minimum sample size filter.
"""

from datetime import date
from backend.storage.database import get_connection


def compute_trust_map(min_sample: int = 2) -> dict:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                promised_by_name AS name,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'fulfilled') AS fulfilled,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (
                    WHERE status = 'pending'
                      AND due_date IS NOT NULL
                      AND due_date < CURRENT_DATE
                ) AS overdue,
                COUNT(*) FILTER (WHERE status = 'expired') AS expired,
                MIN(created_at) AS first_seen,
                MAX(created_at) AS last_seen
            FROM promises
            WHERE promised_by_name IS NOT NULL AND promised_by_name != ''
            GROUP BY promised_by_name
            ORDER BY total DESC
            """
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for r in rows:
        d = dict(r._row)
        total = d["total"]
        if total < min_sample:
            continue
        resolved = (d["fulfilled"] or 0) + (d["expired"] or 0)
        if resolved > 0:
            rate = d["fulfilled"] / resolved
            rate_sample = resolved
        else:
            rate = None  # no resolved sample yet
            rate_sample = 0

        entries.append({
            "name": d["name"],
            "total_promises": total,
            "fulfilled": d["fulfilled"] or 0,
            "pending": d["pending"] or 0,
            "overdue": d["overdue"] or 0,
            "expired": d["expired"] or 0,
            "fulfillment_rate": round(rate, 2) if rate is not None else None,
            "rate_sample": rate_sample,
            "first_seen": str(d["first_seen"])[:10] if d["first_seen"] else None,
            "last_seen": str(d["last_seen"])[:10] if d["last_seen"] else None,
        })

    # Sort: those with data first (by rate desc), then those with only pending (by total desc)
    entries.sort(
        key=lambda e: (e["fulfillment_rate"] is None, -(e["fulfillment_rate"] or 0), -e["total_promises"])
    )

    total_promises = sum(e["total_promises"] for e in entries)
    total_overdue = sum(e["overdue"] for e in entries)

    return {
        "generated_at": date.today().isoformat(),
        "min_sample": min_sample,
        "tracked_people": len(entries),
        "total_promises": total_promises,
        "total_overdue": total_overdue,
        "entries": entries,
    }
