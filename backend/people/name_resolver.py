"""Name resolution — normalize names to canonical forms and split compound assignees.

Solves these problems:
1. Extraction can produce short names ('Alex') while source systems have full names ('Alex Chen')
2. Compound assignees like 'Alex and Sam' need to be split into individual people
3. Junk non-people like 'Team', 'infrastructure team', and 'client feedback' should be filtered
"""

import logging
import re
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.name_resolver")

# Non-person entities that sometimes appear as assignees/speakers
JUNK_NAMES = {
    "team", "everyone", "all", "nobody", "someone", "they",
    "infrastructure team", "client feedback", "client",
    "javier/speaker team", "speaker team", "unassigned", "tbd",
    "n/a", "na", "none", "null", "unknown",
}

# Split compound assignees
COMPOUND_SEPARATORS = [
    r"\s+and\s+",
    r"\s*,\s*",
    r"\s*/\s*",
    r"\s*&\s*",
]
COMPOUND_PATTERN = re.compile("|".join(COMPOUND_SEPARATORS), re.IGNORECASE)


def is_junk_name(name: str) -> bool:
    """Check if a name is actually a junk entry."""
    if not name or not name.strip():
        return True
    lower = name.strip().lower()
    if lower in JUNK_NAMES:
        return True
    # "the XYZ team", "XYZ client", etc.
    if "team" in lower and len(lower.split()) > 1:
        return True
    if lower.endswith(" client") or lower.endswith(" feedback"):
        return True
    return False


def split_compound(name: str) -> list[str]:
    """Split 'Alex and Sam' into ['Alex', 'Sam']."""
    if not name:
        return []

    parts = COMPOUND_PATTERN.split(name.strip())
    result = []
    for p in parts:
        p = p.strip()
        if p and not is_junk_name(p):
            result.append(p)

    # If we got no valid parts but the original isn't junk, return it as-is
    if not result and not is_junk_name(name):
        return [name.strip()]
    return result


def resolve_name(short_name: str) -> str:
    """Resolve a short name to its canonical full name if known.

    Checks the people table for a full name that starts with or contains the short name.
    Returns the original name if no match found.
    """
    if not short_name or is_junk_name(short_name):
        return short_name

    short = short_name.strip()

    # Already a full name? (has space)
    if " " in short:
        return short

    conn = get_connection()
    try:
        # Look for a full name where the first word matches
        rows = conn.execute(
            """SELECT name FROM people
            WHERE email IS NOT NULL AND email != ''
            AND (LOWER(name) LIKE ? OR LOWER(name) LIKE ?)
            ORDER BY total_interactions DESC LIMIT 1""",
            (f"{short.lower()} %", f"% {short.lower()}"),
        ).fetchone()
        if rows:
            return rows["name"]
    except Exception as e:
        logger.debug("Name resolution query failed: %s", e)
    finally:
        conn.close()

    return short


def resolve_names(names: list[str]) -> list[str]:
    """Resolve a list of names, splitting compounds and deduping."""
    resolved = []
    seen = set()

    for name in names:
        if not name:
            continue
        # Split compounds
        for part in split_compound(name):
            canonical = resolve_name(part)
            key = canonical.lower()
            if key not in seen:
                seen.add(key)
                resolved.append(canonical)

    return resolved


def cleanup_junk_people():
    """Remove junk entries from the people table and merge duplicates.

    Returns a dict of rename mappings applied.
    """
    conn = get_connection()
    renames = {}
    deleted = 0
    try:
        rows = conn.execute("SELECT id, name, email FROM people").fetchall()

        # First pass: delete junk and compound names
        for r in rows:
            name = r["name"]
            if is_junk_name(name):
                conn.execute("DELETE FROM people WHERE id = ?", (r["id"],))
                deleted += 1
                continue
            # Split compound check — if name splits into multiple parts, it's a compound
            parts = split_compound(name)
            if len(parts) > 1:
                conn.execute("DELETE FROM people WHERE id = ?", (r["id"],))
                deleted += 1
                continue

        # Second pass: find short names that should be merged into full names
        rows = conn.execute("SELECT id, name, email, total_interactions FROM people").fetchall()
        full_names = {}  # first_word.lower() -> (id, full_name) for people with email
        for r in rows:
            if r["email"] and " " in r["name"]:
                first = r["name"].split()[0].lower()
                # Only track if unambiguous (only one person with this first name)
                if first in full_names:
                    full_names[first] = None  # ambiguous
                else:
                    full_names[first] = (r["id"], r["name"])

        # Delete or merge ambiguous short-name entries
        for r in rows:
            if not r["email"] and " " not in r["name"]:
                key = r["name"].strip().lower()
                if key in full_names and full_names[key] is not None:
                    full_id, full_name = full_names[key]
                    renames[r["name"]] = full_name

                    # Re-point all references to the full name
                    conn.execute(
                        "UPDATE action_items SET assignee = ? WHERE assignee = ?",
                        (full_name, r["name"]),
                    )
                    conn.execute(
                        "UPDATE decisions SET made_by = ? WHERE made_by = ?",
                        (full_name, r["name"]),
                    )
                    try:
                        conn.execute(
                            "UPDATE promises SET promised_by_name = ? WHERE promised_by_name = ?",
                            (full_name, r["name"]),
                        )
                        conn.execute(
                            "UPDATE promises SET promised_to_name = ? WHERE promised_to_name = ?",
                            (full_name, r["name"]),
                        )
                    except Exception:
                        pass

                    conn.execute("DELETE FROM people WHERE id = ?", (r["id"],))
                    deleted += 1

        conn.commit()
    finally:
        conn.close()

    logger.info("Name cleanup: %d deleted, %d renamed", deleted, len(renames))
    return {"deleted": deleted, "renames": renames}
