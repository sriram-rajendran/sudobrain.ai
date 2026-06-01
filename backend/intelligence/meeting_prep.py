"""Pre-meeting preparation — auto-gather context about attendees before meetings.

Pulls from people graph, promises, action items, recent interactions,
and past meeting topics to prepare a briefing for upcoming meetings.
"""

import logging
from datetime import datetime, date
from typing import Optional

from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.meeting_prep")


def prepare_for_meeting(attendee_names: list[str], meeting_title: str = "") -> dict:
    """Generate a pre-meeting briefing for the given attendees.

    Returns context about each attendee:
    - Recent interactions
    - Pending promises (from/to them)
    - Open action items assigned to them
    - Past discussion topics
    - Any overdue commitments
    """
    briefing = {
        "meeting_title": meeting_title,
        "generated_at": datetime.now().isoformat(),
        "attendees": [],
        "shared_context": {},
    }

    conn = get_connection()
    try:
        all_topics = set()
        all_projects = set()

        for name in attendee_names:
            if not name or not name.strip():
                continue
            name = name.strip()
            attendee_info = _get_attendee_context(conn, name)
            briefing["attendees"].append(attendee_info)

            # Collect shared context
            for t in attendee_info.get("recent_topics", []):
                all_topics.add(t)
            for p in attendee_info.get("projects", []):
                all_projects.add(p)

        # Shared items across all attendees
        if len(attendee_names) > 1:
            briefing["shared_context"] = {
                "common_topics": list(all_topics),
                "common_projects": list(all_projects),
            }

    finally:
        conn.close()

    return briefing


def _get_attendee_context(conn, name: str) -> dict:
    """Gather all context for a single attendee."""
    context = {
        "name": name,
        "promises_from_them": [],
        "promises_to_them": [],
        "assigned_tasks": [],
        "recent_topics": [],
        "projects": [],
        "last_interaction": None,
        "warnings": [],
    }

    # Promises they made (pending)
    try:
        rows = conn.execute(
            "SELECT description, due_date FROM promises WHERE promised_by_name LIKE ? AND status='pending'",
            (f"%{name}%",),
        ).fetchall()
        for r in rows:
            item = {"description": r["description"], "due_date": r["due_date"]}
            if r["due_date"] and r["due_date"] < date.today().isoformat():
                item["overdue"] = True
                context["warnings"].append(f"Overdue promise from {name}: {r['description']}")
            context["promises_from_them"].append(item)
    except Exception:
        pass

    # Promises made to them (pending)
    try:
        rows = conn.execute(
            "SELECT description, due_date, promised_by_name FROM promises WHERE promised_to_name LIKE ? AND status='pending'",
            (f"%{name}%",),
        ).fetchall()
        for r in rows:
            item = {"description": r["description"], "due_date": r["due_date"], "from": r["promised_by_name"]}
            if r["due_date"] and r["due_date"] < date.today().isoformat():
                item["overdue"] = True
                context["warnings"].append(f"Overdue promise to {name}: {r['description']}")
            context["promises_to_them"].append(item)
    except Exception:
        pass

    # Tasks assigned to them
    try:
        rows = conn.execute(
            "SELECT text, due_date, project FROM action_items WHERE assignee LIKE ? AND status='pending' ORDER BY due_date ASC",
            (f"%{name}%",),
        ).fetchall()
        for r in rows:
            context["assigned_tasks"].append({
                "text": r["text"], "due_date": r["due_date"], "project": r["project"],
            })
            if r["project"]:
                context["projects"].append(r["project"])
    except Exception:
        pass

    # Recent decisions they were involved in
    try:
        rows = conn.execute(
            "SELECT text, project, created_at FROM decisions WHERE made_by LIKE ? ORDER BY created_at DESC LIMIT 5",
            (f"%{name}%",),
        ).fetchall()
        for r in rows:
            if r["project"]:
                context["projects"].append(r["project"])
    except Exception:
        pass

    # Recent transcript mentions (topics)
    try:
        rows = conn.execute(
            """SELECT s.text FROM segments s
            JOIN transcripts t ON t.id = s.transcript_id
            WHERE s.speaker_label LIKE ? OR s.text LIKE ?
            ORDER BY t.processed_at DESC LIMIT 5""",
            (f"%{name}%", f"%{name}%"),
        ).fetchall()
        for r in rows:
            # Extract rough topic from first 50 chars
            topic = r["text"][:80].strip()
            if topic:
                context["recent_topics"].append(topic)
    except Exception:
        pass

    # Last interaction date
    try:
        from backend.people.graph import init_people_tables
        init_people_tables()
        row = conn.execute(
            "SELECT last_interaction FROM people WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
        if row and row["last_interaction"]:
            context["last_interaction"] = row["last_interaction"]
    except Exception:
        pass

    # Deduplicate
    context["projects"] = list(set(context["projects"]))

    return context


def generate_prep_summary(attendee_names: list[str], meeting_title: str = "") -> str:
    """Generate a human-readable pre-meeting prep summary using local reasoning engine."""
    from backend.ai.local_llm_engine import ask

    briefing = prepare_for_meeting(attendee_names, meeting_title)

    # Build context for local reasoning engine
    parts = []
    if meeting_title:
        parts.append(f"Meeting: {meeting_title}")

    for att in briefing["attendees"]:
        section = [f"\n## {att['name']}"]

        if att["warnings"]:
            section.append("WARNINGS: " + "; ".join(att["warnings"]))
        if att["promises_from_them"]:
            section.append("Promises from them: " + "; ".join(
                p["description"] for p in att["promises_from_them"]
            ))
        if att["promises_to_them"]:
            section.append("Promises to them: " + "; ".join(
                p["description"] for p in att["promises_to_them"]
            ))
        if att["assigned_tasks"]:
            section.append("Their open tasks: " + "; ".join(
                t["text"] for t in att["assigned_tasks"][:5]
            ))
        if att["last_interaction"]:
            section.append(f"Last interaction: {att['last_interaction']}")

        parts.append("\n".join(section))

    context = "\n".join(parts)

    prompt = f"""Generate a concise pre-meeting prep briefing. Be direct and actionable.

Format:
- Key things to remember about each person
- Overdue items to address
- Topics likely to come up
- Suggested talking points

Keep it under 200 words.

Data:
{context}"""

    return ask(prompt, max_wait=60)
