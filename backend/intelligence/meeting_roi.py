"""Meeting ROI score.

For each Fathom meeting (which has transcript + calendar attendees):
- cost = attendee_count × duration_minutes (person-minutes)
- output = action_items_extracted + decisions_extracted + promises_extracted
  attributed to the meeting's transcript
- roi = output / (cost / 60) → items per person-hour

Ranks recent meetings by ROI and flags low-output high-cost ones.
"""

from datetime import datetime, timedelta, timezone
from backend.storage.database import get_connection


def compute_meeting_roi(days: int = 30) -> dict:
    conn = get_connection()
    try:
        # Fathom transcripts from recordings
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Look for recordings that came from fathom (audio_path or mode)
        rows = conn.execute(
            """
            SELECT r.id AS rec_id, r.mode, r.duration_seconds, r.created_at,
                   r.audio_path
            FROM recordings r
            WHERE r.created_at >= ?
              AND r.mode IN ('meeting','fathom_meeting','voice_note')
            ORDER BY r.created_at DESC
            """,
            (since.replace(tzinfo=None),),
        ).fetchall()

        results = []
        for r in rows:
            rec_id = r["rec_id"]
            duration_min = (r["duration_seconds"] or 0) / 60

            # Find linked transcript (participants live inside transcript_json)
            t = conn.execute(
                "SELECT id, transcript_json FROM transcripts WHERE recording_id = ?",
                (rec_id,),
            ).fetchone()

            participants = 1
            transcript_id = None
            if t:
                transcript_id = t["id"]
                try:
                    import json
                    blob = t["transcript_json"]
                    if isinstance(blob, str):
                        blob = json.loads(blob)
                    parts = (blob or {}).get("participants") or []
                    participants = max(1, len(parts))
                except Exception:
                    pass

            # Count extracted knowledge
            ai = conn.execute(
                "SELECT COUNT(*) c FROM action_items WHERE transcript_id = ?",
                (transcript_id,),
            ).fetchone()["c"] if transcript_id else 0
            dec = conn.execute(
                "SELECT COUNT(*) c FROM decisions WHERE transcript_id = ?",
                (transcript_id,),
            ).fetchone()["c"] if transcript_id else 0
            prom = conn.execute(
                "SELECT COUNT(*) c FROM promises WHERE transcript_id = ?",
                (transcript_id,),
            ).fetchone()["c"] if transcript_id else 0

            output = ai + dec + prom
            person_min = participants * duration_min
            roi = (output / (person_min / 60)) if person_min > 0 else 0

            results.append({
                "recording_id": rec_id,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "duration_min": round(duration_min, 1),
                "attendees": participants,
                "person_minutes": round(person_min, 1),
                "action_items": ai,
                "decisions": dec,
                "promises": prom,
                "total_output": output,
                "roi_per_person_hour": round(roi, 2),
            })
    finally:
        conn.close()

    results.sort(key=lambda m: -m["roi_per_person_hour"])

    # Flag low-ROI high-cost meetings
    lowroi = [
        m for m in results
        if m["person_minutes"] >= 30 and m["roi_per_person_hour"] < 0.5
    ]

    return {
        "period_days": days,
        "total_meetings": len(results),
        "avg_roi": round(
            sum(m["roi_per_person_hour"] for m in results) / len(results), 2
        ) if results else 0,
        "low_roi_meetings": lowroi[:10],
        "top_roi_meetings": results[:10],
    }
