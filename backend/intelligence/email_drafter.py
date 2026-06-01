"""Email draft generation — auto-draft follow-up emails after meetings."""

import logging
from backend.ai.local_llm_engine import ask
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.email")


def draft_followup_email(recording_id: str) -> dict:
    """Generate a follow-up email draft from a meeting recording.

    Pulls transcript, extracted knowledge (action items, decisions, promises),
    and attendee info to compose a professional follow-up.
    """
    import json

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT transcript_json FROM transcripts WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
        if not row:
            return {"error": "Transcript not found"}

        transcript = json.loads(row["transcript_json"])
        text = transcript.get("full_transcript", "")[:3000]
        participants = [p.get("label", p.get("speaker_id", ""))
                        for p in transcript.get("participants", [])]

        # Get action items for this transcript
        transcript_id = transcript.get("id", "")
        actions = conn.execute(
            "SELECT text, assignee, due_date FROM action_items WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchall()

        decisions = conn.execute(
            "SELECT text, made_by FROM decisions WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchall()

        promises = []
        try:
            promises = conn.execute(
                "SELECT description, promised_by_name, promised_to_name, due_date FROM promises WHERE transcript_id = ?",
                (transcript_id,),
            ).fetchall()
        except Exception:
            pass
    finally:
        conn.close()

    # Build context
    parts = [f"Meeting transcript (first 3000 chars):\n{text}"]

    if participants:
        parts.append(f"Attendees: {', '.join(participants)}")

    if actions:
        parts.append("Action items:\n" + "\n".join(
            f"- {a['text']} (assigned to: {a['assignee'] or 'TBD'}, due: {a['due_date'] or 'TBD'})"
            for a in actions
        ))

    if decisions:
        parts.append("Decisions made:\n" + "\n".join(
            f"- {d['text']} (by {d['made_by'] or 'team'})" for d in decisions
        ))

    if promises:
        parts.append("Commitments:\n" + "\n".join(
            f"- {p['description']} ({p['promised_by_name']} to {p['promised_to_name']}, due: {p['due_date'] or 'TBD'})"
            for p in promises
        ))

    context = "\n\n".join(parts)

    prompt = f"""Draft a professional follow-up email for this meeting.

Include:
- Brief summary of what was discussed (2-3 sentences)
- Decisions made (bulleted)
- Action items with owners and due dates (bulleted)
- Commitments/promises (bulleted)
- Next steps

Tone: professional but warm. Keep it concise.
Address it to the attendees.

{context}"""

    email_body = ask(prompt, max_wait=60)

    return {
        "recording_id": recording_id,
        "to": participants,
        "subject": f"Follow-up: {transcript.get('fathom', {}).get('title', 'Meeting')} — Action Items & Decisions",
        "body": email_body,
        "action_items_count": len(actions),
        "decisions_count": len(decisions),
    }
