"""Fathom → SudoBrain integration pipeline.

Downloads Fathom recordings, transcribes with Sarvam AI (using Fathom's
speaker identification), and feeds into SudoBrain's knowledge extraction pipeline.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("sudobrain.fathom")

from backend.fathom.client import (
    download_audio,
    extract_speaker_segments,
    fetch_meeting_metadata,
)
from backend.processing.audio_processor import process_audio
from backend.transcription.sarvam_client import transcribe_meeting
from backend.storage import database as db
from backend.ai.local_llm_engine import extract_knowledge as local_llm_extract
from backend.people.graph import register_fathom_speakers

FATHOM_DIR = Path(os.getenv("SUDOBRAIN_DATA_DIR", str(Path.home() / ".sudobrain"))) / "fathom"
RECORDINGS_DIR = FATHOM_DIR / "recordings"
PROCESSED_DIR = FATHOM_DIR / "processed"

for d in [RECORDINGS_DIR, PROCESSED_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _merge_speakers_with_transcript(fathom_segments: list[dict], sarvam_transcript: dict) -> dict:
    """Merge Fathom speaker identification with Sarvam transcription text.

    Fathom gives us: WHO is speaking and WHEN (speaker name, email, timestamps)
    Sarvam gives us: WHAT was said (accurate Tamil+English text)

    For each Sarvam segment, find the overlapping Fathom segment
    to assign the correct speaker name and email.
    """
    if not fathom_segments:
        return sarvam_transcript

    speakers = {}
    for seg in fathom_segments:
        name = seg["speaker_name"]
        if name not in speakers:
            speakers[name] = {
                "speaker_id": name.lower().replace(" ", "_"),
                "label": name,
                "email": seg["speaker_email"],
                "is_self": False,
            }

    sarvam_transcript["participants"] = list(speakers.values())

    for sarvam_seg in sarvam_transcript["segments"]:
        seg_start = sarvam_seg["start_seconds"]
        seg_end = sarvam_seg["end_seconds"]
        seg_mid = (seg_start + seg_end) / 2 if seg_end > seg_start else seg_start

        best_speaker = None
        best_distance = float("inf")

        for fathom_seg in fathom_segments:
            f_start = fathom_seg["start_seconds"]
            f_end = fathom_seg["end_seconds"]

            if f_start <= seg_mid <= f_end:
                best_speaker = fathom_seg
                break

            distance = min(abs(seg_mid - f_start), abs(seg_mid - f_end))
            if distance < best_distance:
                best_distance = distance
                best_speaker = fathom_seg

        if best_speaker:
            name = best_speaker["speaker_name"]
            sarvam_seg["speaker_id"] = name.lower().replace(" ", "_")
            sarvam_seg["speaker_name"] = name
            sarvam_seg["speaker_email"] = best_speaker["speaker_email"]

    return sarvam_transcript


def _save_promise(transcript_id: str, item: dict):
    """Save a promise to the database."""
    conn = db.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id TEXT,
                promised_by_name TEXT,
                promised_to_name TEXT,
                description TEXT NOT NULL,
                detected_text TEXT,
                due_date DATE,
                status TEXT DEFAULT 'pending',
                reminder_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing = conn.execute(
            """
            SELECT id FROM promises
            WHERE transcript_id = ?
              AND LOWER(REGEXP_REPLACE(COALESCE(description, ''), '\\s+', ' ', 'g')) =
                  LOWER(REGEXP_REPLACE(COALESCE(?, ''), '\\s+', ' ', 'g'))
              AND COALESCE(LOWER(promised_by_name), '') = COALESCE(LOWER(?), '')
              AND COALESCE(LOWER(promised_to_name), '') = COALESCE(LOWER(?), '')
            LIMIT 1
            """,
            (
                transcript_id,
                item.get("text", ""),
                item.get("promised_by", ""),
                item.get("promised_to", ""),
            ),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """INSERT INTO promises (transcript_id, promised_by_name, promised_to_name, description, due_date)
            VALUES (?, ?, ?, ?, ?)""",
            (
                transcript_id,
                item.get("promised_by", ""),
                item.get("promised_to", ""),
                item.get("text", ""),
                item.get("due_date"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def run_fathom_pipeline(
    recording_id: str,
    share_url: str,
    num_speakers: int | None = None,
) -> dict:
    """Full Fathom -> SudoBrain pipeline.

    1. Fetch meeting metadata from Fathom API
    2. Download MP3 from Fathom HLS stream
    3. Extract speaker segments (names, emails, timestamps) from Fathom
    4. Process audio -> 16kHz mono WAV
    5. Transcribe with Sarvam AI
    6. Merge Fathom speakers with Sarvam transcript text
    7. Save to SudoBrain database
    8. Run knowledge extraction (action items, decisions, promises)
    9. Register speakers in people graph

    Returns the processing result dict.
    """
    logger.info("Starting Fathom pipeline for recording %s", recording_id)

    # 1. Fetch meeting metadata
    logger.info("Step 1: Fetching meeting metadata...")
    metadata = fetch_meeting_metadata(recording_id, share_url)
    fathom_recording_id = metadata.get("recording_id", str(recording_id))
    meeting_title = metadata.get("title", "Fathom Meeting")
    sudobrain_recording_id = f"fathom_{fathom_recording_id}"
    transcript_id = f"fathom_sarvam_{fathom_recording_id}"
    logger.info("Meeting: %s", meeting_title)

    # 2. Download MP3
    logger.info("Step 2: Downloading MP3 from Fathom...")
    mp3_path = download_audio(
        share_url=share_url,
        recording_id=fathom_recording_id,
        output_dir=str(RECORDINGS_DIR),
    )

    # 3. Get speaker identification from Fathom
    logger.info("Step 3: Extracting speaker data from Fathom...")
    fathom_speakers = extract_speaker_segments(fathom_recording_id)

    # 4. Process audio (MP3 -> 16kHz mono WAV)
    logger.info("Step 4: Processing audio...")
    wav_path = process_audio(mp3_path, str(PROCESSED_DIR))

    # 5. Transcribe with Sarvam AI
    logger.info("Step 5: Transcribing with Sarvam AI...")
    if not num_speakers and fathom_speakers:
        unique_speakers = set(s["speaker_name"] for s in fathom_speakers)
        num_speakers = len(unique_speakers)
        logger.info("Detected %d speakers from Fathom", num_speakers)
    transcript = transcribe_meeting(wav_path, num_speakers)

    # 6. Merge Fathom speakers with Sarvam text
    logger.info("Step 6: Merging Fathom speakers with Sarvam transcript...")
    merged = _merge_speakers_with_transcript(fathom_speakers, transcript)

    # 7. Save with deterministic IDs so retries update the same local records.
    merged["recording_id"] = sudobrain_recording_id
    merged["id"] = transcript_id
    merged["source"] = "fathom_meeting"
    merged["fathom"] = {
        "fathom_recording_id": fathom_recording_id,
        "title": meeting_title,
        "url": metadata.get("url", ""),
        "share_url": metadata.get("share_url", share_url),
        "recording_start_time": metadata.get("recording_start_time", ""),
        "recording_end_time": metadata.get("recording_end_time", ""),
        "recorded_by": metadata.get("recorded_by", {}),
        "calendar_invitees": metadata.get("calendar_invitees", []),
    }

    # Save recording entry
    db.save_recording(sudobrain_recording_id, "fathom_meeting", mp3_path, merged.get("duration_seconds", 0))

    # Save transcript
    db.save_transcript(merged)

    logger.info("Saved to SudoBrain: recording=%s", sudobrain_recording_id)

    # 8. Run knowledge extraction
    knowledge = None
    transcript_text = merged.get("full_transcript", "")
    if transcript_text and len(transcript_text) > 20:
        try:
            logger.info("Step 7: Extracting knowledge with local reasoning engine...")
            knowledge = local_llm_extract(transcript_text)

            if knowledge:
                for item in knowledge.get("action_items", []):
                    db.save_action_item(
                        transcript_id=transcript_id,
                        text=item.get("text", ""),
                        assignee=item.get("assignee"),
                        project=knowledge.get("project"),
                        due_date=item.get("due_date"),
                    )
                for item in knowledge.get("decisions", []):
                    db.save_decision(
                        transcript_id=transcript_id,
                        text=item.get("text", ""),
                        made_by=item.get("made_by"),
                        context=item.get("context"),
                        project=knowledge.get("project"),
                    )
                    try:
                        from backend.intelligence.decisions import save_decision_journal
                        save_decision_journal(
                            transcript_id=transcript_id,
                            text=item.get("text", ""),
                            made_by=item.get("made_by"),
                            reasoning=item.get("context"),
                            confidence=7,
                            domain="work",
                            project_name=knowledge.get("project"),
                        )
                    except Exception as e:
                        logger.warning("Failed to save decision journal entry: %s", e)

                for item in knowledge.get("promises", []):
                    _save_promise(transcript_id, item)

                try:
                    from backend.intelligence.cross_reference import track_recurring_topics
                    topic_names = [t.get("title", "") for t in knowledge.get("topics", [])]
                    track_recurring_topics(topic_names)
                except Exception as e:
                    logger.warning("Failed to track recurring topics: %s", e)

                logger.info(
                    "Extracted: %d actions, %d decisions, %d promises",
                    len(knowledge.get("action_items", [])),
                    len(knowledge.get("decisions", [])),
                    len(knowledge.get("promises", [])),
                )

                # Score meeting effectiveness
                try:
                    from backend.intelligence.meeting_score import score_meeting
                    score = score_meeting(sudobrain_recording_id, knowledge, merged.get("duration_seconds", 0))
                    logger.info("Meeting score: %s/100", score["overall_score"])
                except Exception as e:
                    logger.warning("Meeting scoring failed: %s", e)

                # Check for contradictions
                try:
                    from backend.intelligence.cross_reference import check_contradictions
                    findings = check_contradictions(transcript_text)
                    if findings:
                        logger.info("Cross-reference: %d findings", len(findings))
                except Exception as e:
                    logger.warning("Cross-reference check failed: %s", e)

                # Ingest into Neo4j knowledge graph
                try:
                    from backend.graph.neo4j_client import ingest_knowledge
                    participant_names = [p.get("label", p.get("speaker_id", ""))
                                         for p in merged.get("participants", [])]
                    ingest_knowledge(
                        knowledge, transcript_id,
                        meeting_date=metadata.get("recording_start_time"),
                        participants=participant_names,
                    )
                    logger.info("Graph ingestion complete")
                except Exception as e:
                    logger.warning("Graph ingestion failed: %s", e)

        except Exception as e:
            logger.error("Knowledge extraction failed: %s", e)

    # 9. Sentiment analysis
    if transcript_text and len(transcript_text) > 50:
        try:
            from backend.intelligence.sentiment import analyze_transcript_sentiment
            sentiment = analyze_transcript_sentiment(
                transcript_text[:2000],
                recording_id=sudobrain_recording_id,
                transcript_id=transcript_id,
            )
            logger.info("Sentiment: %s (score: %s)", sentiment.get("label"), sentiment.get("score"))
        except Exception as e:
            logger.warning("Sentiment analysis failed: %s", e)

    # 10. Register Fathom speakers in people graph
    if fathom_speakers:
        logger.info("Step 8: Registering speakers in people graph...")
        register_fathom_speakers(
            fathom_speakers,
            transcript_id=transcript_id,
            recording_id=sudobrain_recording_id,
            meeting_date=metadata.get("recording_start_time"),
        )

    logger.info(
        "Fathom pipeline complete: title=%s, duration=%.1fs, participants=%s, segments=%d",
        meeting_title,
        merged.get("duration_seconds", 0),
        [p.get("label", p.get("speaker_id")) for p in merged.get("participants", [])],
        len(merged.get("segments", [])),
    )

    return {
        "recording_id": sudobrain_recording_id,
        "transcript_id": transcript_id,
        "fathom_recording_id": fathom_recording_id,
        "title": meeting_title,
        "duration_seconds": merged.get("duration_seconds", 0),
        "participants": [p.get("label", p.get("speaker_id")) for p in merged.get("participants", [])],
        "segments_count": len(merged.get("segments", [])),
        "knowledge": knowledge,
        "status": "completed",
    }
