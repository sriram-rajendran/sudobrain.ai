"""Sentiment & emotion tracking — analyze meeting tone and track trends."""

import logging
from datetime import datetime
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.sentiment")


def init_sentiment_table():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meeting_sentiment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT,
                transcript_id TEXT,
                sentiment_score REAL,
                sentiment_label TEXT,
                reasoning TEXT,
                key_moments TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_recording ON meeting_sentiment(recording_id)")
        conn.commit()
    finally:
        conn.close()


def analyze_transcript_sentiment(transcript_text: str, recording_id: str = None,
                                  transcript_id: str = None) -> dict:
    """Analyze sentiment of a transcript and store the result.

    Tries Ollama first (free, fast), falls back to TextBlob (basic).
    """
    init_sentiment_table()

    result = _analyze_with_ollama(transcript_text)
    if not result:
        result = _analyze_with_textblob(transcript_text)

    # Store result
    if result and recording_id:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO meeting_sentiment
                (recording_id, transcript_id, sentiment_score, sentiment_label, reasoning)
                VALUES (?, ?, ?, ?, ?)""",
                (recording_id, transcript_id, result["score"],
                 result["label"], result.get("reasoning", "")),
            )
            conn.commit()
        finally:
            conn.close()

    return result


def _analyze_with_ollama(text: str) -> dict:
    """Use local Ollama for sentiment analysis — routes to fast tier."""
    try:
        from backend.ai.model_router import analyze_sentiment
        result = analyze_sentiment(text[:2000])
        if result and result.get("label") != "neutral" or result.get("reasoning", "") != "no model available":
            return result
    except Exception as e:
        logger.debug("Model router sentiment failed: %s", e)
    return None


def _analyze_with_textblob(text: str) -> dict:
    """Fallback: basic sentiment via TextBlob."""
    try:
        from textblob import TextBlob
        blob = TextBlob(text[:2000])
        polarity = blob.sentiment.polarity  # -1 to 1

        if polarity > 0.1:
            label = "positive"
        elif polarity < -0.1:
            label = "negative"
        else:
            label = "neutral"

        return {"score": round(polarity, 2), "label": label, "reasoning": "TextBlob analysis"}
    except Exception as e:
        logger.warning("TextBlob sentiment failed: %s", e)
        return {"score": 0.0, "label": "neutral", "reasoning": "analysis unavailable"}


def get_sentiment_trend(days: int = 30) -> list[dict]:
    """Get sentiment scores over time."""
    init_sentiment_table()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT recording_id, sentiment_score, sentiment_label, created_at
            FROM meeting_sentiment
            WHERE created_at >= CURRENT_DATE - (? || ' days')::INTERVAL
            ORDER BY created_at ASC""",
            (str(days),),
        ).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


def get_sentiment_by_person(person_name: str) -> list[dict]:
    """Get sentiment for meetings involving a specific person."""
    init_sentiment_table()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT ms.sentiment_score, ms.sentiment_label, ms.created_at
            FROM meeting_sentiment ms
            JOIN transcripts t ON t.recording_id = ms.recording_id
            JOIN segments s ON s.transcript_id = t.id
            WHERE s.speaker_label LIKE ?
            GROUP BY ms.id
            ORDER BY ms.created_at DESC LIMIT 20""",
            (f"%{person_name}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
