"""Personal CRM — relationship intelligence, health scoring, stale contact alerts."""

import logging
from datetime import datetime, date, timedelta
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.crm")


def get_relationship_health() -> list[dict]:
    """Get all contacts with health scores and interaction analysis.

    Health degrades over time without interaction.
    """
    from backend.people.graph import init_people_tables
    init_people_tables()

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*,
                (SELECT COUNT(*) FROM promises WHERE promised_by_name = p.name AND status = 'pending') as promises_from,
                (SELECT COUNT(*) FROM promises WHERE promised_to_name = p.name AND status = 'pending') as promises_to,
                (SELECT COUNT(*) FROM action_items WHERE assignee = p.name AND status = 'pending') as pending_tasks
            FROM people p WHERE p.is_self = FALSE
            ORDER BY p.last_interaction DESC
        """).fetchall()

        contacts = []
        today = date.today()

        for r in rows:
            contact = dict(r)

            # Calculate health score based on recency
            last = r["last_interaction"]
            if last:
                try:
                    last_date = date.fromisoformat(last[:10])
                    days_since = (today - last_date).days

                    if days_since <= 7:
                        health = 100
                        status = "active"
                    elif days_since <= 14:
                        health = 85
                        status = "good"
                    elif days_since <= 30:
                        health = 65
                        status = "cooling"
                    elif days_since <= 60:
                        health = 40
                        status = "stale"
                    else:
                        health = max(10, 100 - days_since)
                        status = "dormant"

                    contact["health_score"] = health
                    contact["health_status"] = status
                    contact["days_since_contact"] = days_since
                except (ValueError, TypeError):
                    contact["health_score"] = 50
                    contact["health_status"] = "unknown"
                    contact["days_since_contact"] = None
            else:
                contact["health_score"] = 0
                contact["health_status"] = "no_interaction"
                contact["days_since_contact"] = None

            contacts.append(contact)

        return contacts
    finally:
        conn.close()


def get_stale_contacts(days_threshold: int = 30) -> list[dict]:
    """Get contacts you haven't interacted with in N days."""
    all_contacts = get_relationship_health()
    return [
        c for c in all_contacts
        if c.get("days_since_contact") and c["days_since_contact"] >= days_threshold
    ]


def get_top_contacts(limit: int = 10, days: int = 30) -> list[dict]:
    """Get your most frequent contacts in the last N days."""
    from backend.people.graph import init_people_tables
    init_people_tables()

    conn = get_connection()
    try:
        threshold = (date.today() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT p.name, p.email, p.role, COUNT(pi.id) as interactions,
                   MAX(pi.interaction_date) as last_interaction,
                   SUM(pi.duration_minutes) as total_minutes
            FROM person_interactions pi
            JOIN people p ON p.id = pi.person_id
            WHERE pi.interaction_date >= ? AND p.is_self = FALSE
            GROUP BY p.id
            ORDER BY interactions DESC
            LIMIT ?
        """, (threshold, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_contact_history(person_name: str) -> dict:
    """Get full interaction history with a person."""
    from backend.people.graph import init_people_tables
    init_people_tables()

    conn = get_connection()
    try:
        person = conn.execute(
            "SELECT * FROM people WHERE LOWER(name) = LOWER(?)", (person_name,)
        ).fetchone()
        if not person:
            return {"error": f"Person '{person_name}' not found"}

        person_dict = dict(person)
        person_id = person["id"]

        # Interactions timeline
        interactions = conn.execute("""
            SELECT pi.interaction_date, pi.summary, pi.duration_minutes, r.mode
            FROM person_interactions pi
            LEFT JOIN recordings r ON r.id = pi.recording_id
            WHERE pi.person_id = ?
            ORDER BY pi.interaction_date DESC LIMIT 20
        """, (person_id,)).fetchall()
        person_dict["interaction_history"] = [dict(i) for i in interactions]

        # Promises
        try:
            promises = conn.execute("""
                SELECT description, due_date, status, promised_by_name, promised_to_name
                FROM promises
                WHERE promised_by_name LIKE ? OR promised_to_name LIKE ?
                ORDER BY created_at DESC
            """, (f"%{person_name}%", f"%{person_name}%")).fetchall()
            person_dict["promises"] = [dict(p) for p in promises]
        except Exception:
            person_dict["promises"] = []

        # Action items
        tasks = conn.execute(
            "SELECT text, due_date, status, project FROM action_items WHERE assignee LIKE ? ORDER BY created_at DESC",
            (f"%{person_name}%",),
        ).fetchall()
        person_dict["tasks"] = [dict(t) for t in tasks]

        # Decisions
        decs = conn.execute(
            "SELECT text, context, project, created_at FROM decisions WHERE made_by LIKE ? ORDER BY created_at DESC LIMIT 10",
            (f"%{person_name}%",),
        ).fetchall()
        person_dict["decisions"] = [dict(d) for d in decs]

        return person_dict
    finally:
        conn.close()
