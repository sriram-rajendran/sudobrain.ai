"""Meeting Intelligence — score meeting effectiveness."""

from backend.storage.database import get_connection


def init_meeting_scores():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meeting_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id TEXT UNIQUE,
            overall_score INTEGER,
            decision_count INTEGER DEFAULT 0,
            action_item_count INTEGER DEFAULT 0,
            promise_count INTEGER DEFAULT 0,
            topic_count INTEGER DEFAULT 0,
            duration_minutes REAL,
            suggestions TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS decision_count INTEGER DEFAULT 0;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS action_item_count INTEGER DEFAULT 0;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS promise_count INTEGER DEFAULT 0;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS topic_count INTEGER DEFAULT 0;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS duration_minutes REAL;
        ALTER TABLE meeting_scores ADD COLUMN IF NOT EXISTS suggestions TEXT;
    """)
    conn.commit()
    conn.close()


def score_meeting(recording_id: str, knowledge: dict, duration_seconds: float = 0) -> dict:
    """Score a meeting based on extracted knowledge.

    Score = weighted sum of:
    - Decision density (decisions per hour): 30%
    - Action item output (items per hour): 30%
    - Promise tracking (commitments made): 20%
    - Topic coverage: 20%
    """
    init_meeting_scores()

    decisions = len(knowledge.get("decisions", []))
    actions = len(knowledge.get("action_items", []))
    promises = len(knowledge.get("promises", []))
    topics = len(knowledge.get("topics", []))
    duration_min = max(duration_seconds / 60, 1)
    duration_hr = max(duration_min / 60, 0.1)

    # Score components (0-100 each)
    decision_score = min(100, int(decisions / duration_hr * 25))  # 4 decisions/hr = 100
    action_score = min(100, int(actions / duration_hr * 15))      # ~7 actions/hr = 100
    promise_score = min(100, promises * 30)                        # 3+ promises = 90+
    topic_score = min(100, topics * 25)                            # 4 topics = 100

    overall = int(
        decision_score * 0.3 +
        action_score * 0.3 +
        promise_score * 0.2 +
        topic_score * 0.2
    )

    # Generate suggestions
    suggestions = []
    if decisions == 0:
        suggestions.append("No decisions were made — consider scheduling a focused decision meeting")
    if actions == 0:
        suggestions.append("No action items assigned — meetings should produce clear next steps")
    if duration_min > 60 and decisions + actions < 3:
        suggestions.append(f"Long meeting ({int(duration_min)}min) with few outputs — consider making it shorter or async")

    # Save to DB
    conn = get_connection()
    conn.execute(
        """INSERT INTO meeting_scores
        (recording_id, overall_score, decision_count, action_item_count, promise_count, topic_count, duration_minutes, suggestions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (recording_id) DO UPDATE SET
            overall_score = EXCLUDED.overall_score,
            decision_count = EXCLUDED.decision_count,
            action_item_count = EXCLUDED.action_item_count,
            promise_count = EXCLUDED.promise_count,
            topic_count = EXCLUDED.topic_count,
            duration_minutes = EXCLUDED.duration_minutes,
            suggestions = EXCLUDED.suggestions""",
        (recording_id, overall, decisions, actions, promises, topics, duration_min, str(suggestions)),
    )
    conn.commit()
    conn.close()

    return {
        "recording_id": recording_id,
        "overall_score": overall,
        "decisions": decisions,
        "action_items": actions,
        "promises": promises,
        "topics": topics,
        "duration_minutes": round(duration_min, 1),
        "suggestions": suggestions,
    }


def get_meeting_score(recording_id: str) -> dict:
    init_meeting_scores()
    conn = get_connection()
    row = conn.execute("SELECT * FROM meeting_scores WHERE recording_id = ?", (recording_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
