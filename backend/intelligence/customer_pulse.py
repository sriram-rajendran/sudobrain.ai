"""Customer pulse — external relationship intelligence.

Groups external Gmail senders by organization (email domain) and scores:
- contact_count: total emails exchanged
- last_contact: most recent email
- days_since: days since last contact
- recent_trend: count in last 14d vs prior 14d
- status: "active" / "cooling" / "silent" / "going_quiet"
"""

import os
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()
SELF_DOMAIN = SELF_EMAIL.split("@")[-1] if "@" in SELF_EMAIL else ""
INTERNAL_DOMAINS = {SELF_DOMAIN}


def compute_customer_pulse() -> dict:
    conn = get_connection()
    try:
        # Outbound + inbound from external orgs only
        rows = conn.execute(
            """
            SELECT LOWER(from_email) AS email,
                   from_name AS name,
                   date AS ts,
                   subject
            FROM gmail_messages
            WHERE from_email IS NOT NULL AND from_email != ''
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"organizations": []}

    # Group by domain
    orgs: dict[str, dict] = {}
    for r in rows:
        email = (r["email"] or "").strip()
        if "@" not in email:
            continue
        domain = email.split("@", 1)[1]
        if domain in INTERNAL_DOMAINS:
            continue
        # Skip noreply/notifications/automated
        if any(skip in email for skip in ("noreply", "no-reply", "notifications", "updates", "digest")):
            continue

        if domain not in orgs:
            orgs[domain] = {
                "domain": domain,
                "contacts": set(),
                "emails": [],
            }
        orgs[domain]["contacts"].add(email)
        orgs[domain]["emails"].append({
            "email": email,
            "name": r["name"],
            "ts": r["ts"],
            "subject": r["subject"],
        })

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=14)
    prior_cutoff = now - timedelta(days=28)

    result = []
    for domain, data in orgs.items():
        emails = sorted(data["emails"], key=lambda e: e["ts"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        last_ts = emails[0]["ts"]
        days_since = (now - last_ts).days if last_ts else None

        recent = sum(1 for e in emails if e["ts"] and e["ts"] >= recent_cutoff)
        prior = sum(1 for e in emails if e["ts"] and prior_cutoff <= e["ts"] < recent_cutoff)

        if recent > 0 and prior == 0:
            status = "new"
        elif recent == 0 and prior > 0:
            status = "going_quiet"
        elif recent == 0 and prior == 0:
            status = "silent"
        elif recent < prior * 0.5 and prior >= 2:
            status = "cooling"
        else:
            status = "active"

        # Sample subjects for context
        last_subjects = [e["subject"] for e in emails[:3] if e["subject"]]

        result.append({
            "domain": domain,
            "total_emails": len(emails),
            "unique_senders": len(data["contacts"]),
            "contact_sample": sorted(data["contacts"])[:3],
            "last_contact": last_ts.isoformat() if last_ts else None,
            "days_since": days_since,
            "recent_14d": recent,
            "prior_14d": prior,
            "status": status,
            "last_subjects": last_subjects,
        })

    # Sort: going_quiet + cooling first, then active
    priority = {"going_quiet": 0, "cooling": 1, "silent": 2, "new": 3, "active": 4}
    result.sort(key=lambda o: (priority.get(o["status"], 9), -o["total_emails"]))

    flagged = [o for o in result if o["status"] in ("going_quiet", "cooling")]

    return {
        "generated_at": now.isoformat(),
        "total_orgs": len(result),
        "flagged_count": len(flagged),
        "organizations": result,
    }
