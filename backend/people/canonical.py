"""Canonical people loader.

Builds the `people` table from authoritative email-bearing sources:
- slack_users
- linear_members
- gmail_messages (from_email + parsed to_emails)
- fathom invitees (optional)
- calendar attendees (optional)

Key is normalized email. Populates `person_identities` for cross-source lookup.
"""

import json
import logging
import os
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.people.canonical")

SELF_EMAIL = os.getenv("SELF_EMAIL", "").lower()


def init_identity_table():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS person_identities (
                id SERIAL PRIMARY KEY,
                person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                display_name TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_person_identities_person ON person_identities(person_id);
            CREATE INDEX IF NOT EXISTS idx_person_identities_source ON person_identities(source);
        """)
        conn.commit()
    finally:
        conn.close()


def _normalize_email(e: str) -> str:
    return (e or "").strip().lower()


def _org_from_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1]


def _best_name(candidates: list[str]) -> str:
    """Pick the longest non-empty, non-email-looking name."""
    valid = []
    for c in candidates:
        if not c:
            continue
        c = c.strip()
        if "@" in c and " " not in c:
            continue  # email literal
        valid.append(c)
    if not valid:
        return ""
    return max(valid, key=len)


def collect_identities() -> dict[str, dict]:
    """Return {normalized_email: {name, identities: [(source, source_id, display_name)]}}"""
    conn = get_connection()
    people: dict[str, dict] = {}

    def add(email: str, name: str, source: str, source_id: str):
        e = _normalize_email(email)
        if not e or "@" not in e:
            return
        if e not in people:
            people[e] = {"email": e, "names": [], "identities": []}
        if name:
            people[e]["names"].append(name)
        people[e]["identities"].append((source, source_id, name or ""))

    try:
        # slack_users
        for r in conn.execute(
            "SELECT id, name, real_name, email FROM slack_users "
            "WHERE email IS NOT NULL AND email != '' AND is_bot = FALSE AND deleted = FALSE"
        ).fetchall():
            add(r["email"], r["real_name"] or r["name"], "slack", r["id"])

        # linear_members
        for r in conn.execute(
            "SELECT id, name, email, display_name FROM linear_members "
            "WHERE email IS NOT NULL AND email != ''"
        ).fetchall():
            add(r["email"], r["name"] or r["display_name"], "linear", r["id"])

        # gmail senders (external + internal)
        for r in conn.execute(
            "SELECT DISTINCT from_email, from_name FROM gmail_messages "
            "WHERE from_email IS NOT NULL AND from_email != ''"
        ).fetchall():
            add(r["from_email"], r["from_name"] or "", "gmail_sender", r["from_email"])

        # gmail recipients (from to_emails JSON — each element may contain
        # multiple comma-separated RFC822 addresses)
        from email.utils import getaddresses
        for r in conn.execute(
            "SELECT DISTINCT to_emails FROM gmail_messages "
            "WHERE to_emails IS NOT NULL AND to_emails != ''"
        ).fetchall():
            try:
                chunks = json.loads(r["to_emails"] or "[]")
                for name, email in getaddresses(chunks):
                    if "@" in email:
                        add(email, name, "gmail_recipient", email.lower())
            except Exception:
                pass
    finally:
        conn.close()

    return people


def load_canonical() -> dict:
    """Write canonical people + identities. Returns summary."""
    init_identity_table()
    people_map = collect_identities()

    conn = get_connection()
    created = 0
    updated = 0
    identities_linked = 0
    try:
        for email, data in people_map.items():
            name = _best_name(data["names"]) or email.split("@", 1)[0]
            org = _org_from_email(email)
            is_self = email == SELF_EMAIL

            # Upsert into people
            row = conn.execute(
                "SELECT id FROM people WHERE LOWER(email) = ?", (email,)
            ).fetchone()

            if row:
                person_id = row["id"]
                conn.execute(
                    "UPDATE people SET name = ?, organization = ?, is_self = ? WHERE id = ?",
                    (name, org, is_self, person_id),
                )
                updated += 1
            else:
                cur = conn.execute(
                    "INSERT INTO people (name, email, organization, is_self, relationship_type, health_score) "
                    "VALUES (?, ?, ?, ?, 'work', 100.0)",
                    (name, email, org, is_self),
                )
                person_id = cur.lastrowid
                created += 1

            # Link identities
            for source, source_id, display_name in data["identities"]:
                conn.execute(
                    "INSERT INTO person_identities (person_id, source, source_id, display_name) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (source, source_id) DO UPDATE SET "
                    "person_id = EXCLUDED.person_id, display_name = EXCLUDED.display_name",
                    (person_id, source, source_id, display_name),
                )
                identities_linked += 1

            # Back-link slack_users.person_id / linear_members.person_id
            conn.execute(
                "UPDATE slack_users SET person_id = ? WHERE LOWER(email) = ?",
                (person_id, email),
            )
            conn.execute(
                "UPDATE linear_members SET person_id = ? WHERE LOWER(email) = ?",
                (person_id, email),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "total_people": len(people_map),
        "created": created,
        "updated": updated,
        "identities_linked": identities_linked,
    }


def resolve_by_email(email: str) -> int | None:
    """Return person_id for a given email, or None."""
    e = _normalize_email(email)
    if not e:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM people WHERE LOWER(email) = ?", (e,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def resolve_by_name(name: str, threshold: float = 0.85) -> int | None:
    """Fuzzy match a name against canonical people. Returns person_id or None."""
    if not name:
        return None
    from difflib import SequenceMatcher
    n = name.strip().lower()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM people").fetchall()
    finally:
        conn.close()

    best_id, best_score = None, 0.0
    for r in rows:
        if not r["name"]:
            continue
        score = SequenceMatcher(None, n, r["name"].lower()).ratio()
        if score > best_score:
            best_score = score
            best_id = r["id"]
    return best_id if best_score >= threshold else None
