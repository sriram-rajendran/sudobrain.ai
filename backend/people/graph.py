"""People graph — auto-builds profiles from transcripts, tracks interactions and promises."""

import re
from datetime import datetime
from backend.storage.database import get_connection


def init_people_tables():
    """Create people-related tables."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            role TEXT,
            organization TEXT,
            relationship_type TEXT DEFAULT 'work',
            first_interaction DATE,
            last_interaction DATE,
            total_interactions INTEGER DEFAULT 0,
            health_score REAL DEFAULT 100,
            notes TEXT,
            is_self BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS person_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER REFERENCES people(id),
            transcript_id TEXT,
            recording_id TEXT,
            interaction_date DATETIME,
            duration_minutes REAL,
            topics TEXT,
            summary TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Migrate: add email column if missing (for existing databases)
    try:
        conn.execute("SELECT email FROM people LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE people ADD COLUMN email TEXT")
        conn.commit()

    conn.close()


def get_or_create_person(name: str, email: str = None) -> int:
    """Get person by name (or email) or create new profile. Returns person ID."""
    init_people_tables()
    name = name.strip()
    if not name:
        return -1

    conn = get_connection()

    # Try matching by email first (more reliable than name)
    row = None
    if email:
        row = conn.execute("SELECT id FROM people WHERE LOWER(email) = LOWER(?)", (email,)).fetchone()

    # Fall back to name match
    if not row:
        row = conn.execute("SELECT id FROM people WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()

    if row:
        person_id = row["id"]
        # Update email if we have one and the record doesn't
        if email:
            conn.execute(
                "UPDATE people SET email = ? WHERE id = ? AND (email IS NULL OR email = '')",
                (email, person_id),
            )
            conn.commit()
    else:
        cursor = conn.execute(
            "INSERT INTO people (name, email, first_interaction) VALUES (?, ?, ?)",
            (name, email, datetime.now().strftime("%Y-%m-%d")),
        )
        person_id = cursor.lastrowid
        conn.commit()

    conn.close()
    return person_id


def record_interaction(person_id: int, transcript_id: str, recording_id: str = None,
                       date: str = None, summary: str = None):
    """Log an interaction with a person."""
    if person_id < 0:
        return

    init_people_tables()
    conn = get_connection()

    interaction_date = date or datetime.now().isoformat()

    conn.execute(
        """INSERT INTO person_interactions (person_id, transcript_id, recording_id, interaction_date, summary)
        VALUES (?, ?, ?, ?, ?)""",
        (person_id, transcript_id, recording_id, interaction_date, summary),
    )

    # Update person stats
    conn.execute(
        """UPDATE people SET
            last_interaction = ?,
            total_interactions = total_interactions + 1
        WHERE id = ?""",
        (interaction_date[:10], person_id),
    )

    conn.commit()
    conn.close()


def populate_from_knowledge():
    """Scan action items, decisions, promises for person names and create/update profiles.

    Splits compound names (e.g. 'Alex and Sam') into individuals and
    resolves short names to canonical full names.
    """
    from backend.people.name_resolver import resolve_names, is_junk_name
    init_people_tables()
    conn = get_connection()

    raw_names = set()

    # From action items
    rows = conn.execute("SELECT assignee, assigned_by FROM action_items").fetchall()
    for r in rows:
        if r["assignee"]: raw_names.add(r["assignee"])
        if r["assigned_by"]: raw_names.add(r["assigned_by"])

    # From decisions
    rows = conn.execute("SELECT made_by FROM decisions").fetchall()
    for r in rows:
        if r["made_by"]: raw_names.add(r["made_by"])

    # From promises
    try:
        rows = conn.execute("SELECT promised_by_name, promised_to_name FROM promises").fetchall()
        for r in rows:
            if r["promised_by_name"]: raw_names.add(r["promised_by_name"])
            if r["promised_to_name"]: raw_names.add(r["promised_to_name"])
    except Exception:
        pass

    # Resolve and split compounds
    names = set()
    for n in raw_names:
        if is_junk_name(n):
            continue
        for resolved in resolve_names([n]):
            names.add(resolved)

    conn.close()

    # Filter out generic names
    skip = {"team", "unassigned", "system", "null", "none", ""}
    names = {n.strip() for n in names if n.strip().lower() not in skip}

    created = 0
    for name in names:
        pid = get_or_create_person(name)
        if pid > 0:
            created += 1

    import os
    self_email = os.getenv("SELF_EMAIL", "").strip().lower()
    if self_email:
        conn = get_connection()
        conn.execute("UPDATE people SET is_self = TRUE WHERE LOWER(email) = ?", (self_email,))
        conn.commit()
        conn.close()

    import logging
    logging.getLogger("sudobrain.people").info("Populated %d people from knowledge base", created)
    return created


def register_fathom_speakers(
    speaker_segments: list[dict],
    transcript_id: str,
    recording_id: str = None,
    meeting_date: str = None,
) -> dict[str, int]:
    """Register speakers from Fathom's speaker data into the people graph.

    Takes the speaker segments from fathom.client.extract_speaker_segments()
    and creates/updates people with their email addresses.

    Returns a mapping of speaker_name -> person_id.
    """
    seen = {}
    for seg in speaker_segments:
        name = seg.get("speaker_name", "").strip()
        email = seg.get("speaker_email", "").strip()
        if not name or name == "Unknown":
            continue
        if name in seen:
            continue

        person_id = get_or_create_person(name, email)
        if person_id > 0:
            record_interaction(
                person_id,
                transcript_id=transcript_id,
                recording_id=recording_id,
                date=meeting_date,
                summary="Fathom meeting",
            )
            seen[name] = person_id

    print(f"[People] Registered {len(seen)} Fathom speakers: {list(seen.keys())}")
    return seen


def get_all_people() -> list:
    """Get all people with their stats."""
    init_people_tables()
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*,
            (SELECT COUNT(*) FROM promises WHERE promised_by_name = p.name AND status = 'pending') as pending_promises_from,
            (SELECT COUNT(*) FROM promises WHERE promised_to_name = p.name AND status = 'pending') as pending_promises_to,
            (SELECT COUNT(*) FROM action_items WHERE assignee = p.name AND status = 'pending') as pending_tasks
        FROM people p
        WHERE p.is_self = FALSE
        ORDER BY p.last_interaction DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_person_detail(person_id: int) -> dict:
    """Get detailed person profile with interaction timeline and promises."""
    init_people_tables()
    conn = get_connection()

    person = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if not person:
        conn.close()
        return None

    person_dict = dict(person)
    name = person_dict["name"]

    # Interaction timeline
    interactions = conn.execute("""
        SELECT pi.*, r.mode FROM person_interactions pi
        LEFT JOIN recordings r ON r.id = pi.recording_id
        WHERE pi.person_id = ?
        ORDER BY pi.interaction_date DESC LIMIT 20
    """, (person_id,)).fetchall()
    person_dict["interactions"] = [dict(i) for i in interactions]

    # Promises involving this person
    promises = conn.execute("""
        SELECT * FROM promises
        WHERE promised_by_name = ? OR promised_to_name = ?
        ORDER BY created_at DESC
    """, (name, name)).fetchall()
    person_dict["promises"] = [dict(p) for p in promises]

    # Action items assigned to this person
    tasks = conn.execute("""
        SELECT * FROM action_items WHERE assignee = ? AND status = 'pending'
        ORDER BY due_date ASC
    """, (name,)).fetchall()
    person_dict["tasks"] = [dict(t) for t in tasks]

    conn.close()
    return person_dict
