"""Decision Journal — log decisions with reasoning, track outcomes, build calibration."""

from datetime import datetime, date, timedelta
from backend.storage.database import get_connection


def init_decisions_journal():
    """Create decisions journal tables."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decisions_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id TEXT,
            text TEXT NOT NULL,
            alternatives TEXT,
            reasoning TEXT,
            confidence INTEGER CHECK(confidence BETWEEN 1 AND 10),
            expected_outcome TEXT,
            evaluation_date DATE,
            domain TEXT,
            project_name TEXT,
            made_by TEXT,
            source TEXT DEFAULT 'meeting',
            outcome TEXT,
            outcome_notes TEXT,
            outcome_date DATE,
            was_correct BOOLEAN,
            status TEXT DEFAULT 'tracked',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS calibration_data (
            confidence_level INTEGER,
            domain TEXT,
            total_decisions INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            accuracy_pct REAL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (confidence_level, domain)
        );
    """)
    conn.commit()
    conn.close()


def save_decision_journal(transcript_id: str, text: str, made_by: str = None,
                           reasoning: str = None, alternatives: str = None,
                           confidence: int = 5, expected_outcome: str = None,
                           evaluation_date: str = None, domain: str = "work",
                           project_name: str = None, source: str = "meeting") -> int:
    """Save a decision to the journal. Returns the decision ID."""
    init_decisions_journal()
    conn = get_connection()

    # Default evaluation date: 3 months from now
    if not evaluation_date:
        eval_date = (date.today() + timedelta(days=90)).isoformat()
    else:
        eval_date = evaluation_date

    cursor = conn.execute(
        """INSERT INTO decisions_journal
        (transcript_id, text, alternatives, reasoning, confidence, expected_outcome,
         evaluation_date, domain, project_name, made_by, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (transcript_id, text, alternatives, reasoning, confidence, expected_outcome,
         eval_date, domain, project_name, made_by, source),
    )
    decision_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return decision_id


def get_all_decisions(status: str = None, domain: str = None) -> list:
    """Get all decisions, optionally filtered."""
    init_decisions_journal()
    conn = get_connection()

    query = "SELECT * FROM decisions_journal WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if domain:
        query += " AND domain = ?"
        params.append(domain)

    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_decision(decision_id: int) -> dict:
    """Get a single decision with full details."""
    init_decisions_journal()
    conn = get_connection()
    row = conn.execute("SELECT * FROM decisions_journal WHERE id = ?", (decision_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def evaluate_decision(decision_id: int, outcome: str, outcome_notes: str = None,
                       was_correct: bool = None) -> bool:
    """Record the outcome of a decision."""
    init_decisions_journal()
    conn = get_connection()

    result = conn.execute(
        """UPDATE decisions_journal SET
            outcome = ?, outcome_notes = ?, outcome_date = ?,
            was_correct = ?, status = 'evaluated'
        WHERE id = ?""",
        (outcome, outcome_notes, date.today().isoformat(), was_correct, decision_id),
    )
    conn.commit()

    # Update calibration data
    if was_correct is not None:
        row = conn.execute("SELECT confidence, domain FROM decisions_journal WHERE id = ?", (decision_id,)).fetchone()
        if row:
            _update_calibration(row["confidence"], row["domain"] or "work", was_correct)

    conn.close()
    return result.rowcount > 0


def get_pending_evaluations() -> list:
    """Get decisions that are due for evaluation."""
    init_decisions_journal()
    conn = get_connection()
    today = date.today().isoformat()
    rows = conn.execute(
        """SELECT * FROM decisions_journal
        WHERE status = 'tracked' AND evaluation_date IS NOT NULL AND evaluation_date <= ?
        ORDER BY evaluation_date ASC""",
        (today,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_calibration() -> list:
    """Get calibration data — confidence vs actual accuracy."""
    init_decisions_journal()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM calibration_data ORDER BY confidence_level"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _update_calibration(confidence: int, domain: str, was_correct: bool):
    """Update calibration data for a confidence level."""
    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM calibration_data WHERE confidence_level = ? AND domain = ?",
        (confidence, domain),
    ).fetchone()

    if row:
        total = row["total_decisions"] + 1
        correct = row["correct_count"] + (1 if was_correct else 0)
        accuracy = (correct / total) * 100
        conn.execute(
            """UPDATE calibration_data SET
                total_decisions = ?, correct_count = ?, accuracy_pct = ?, updated_at = ?
            WHERE confidence_level = ? AND domain = ?""",
            (total, correct, accuracy, datetime.now().isoformat(), confidence, domain),
        )
    else:
        conn.execute(
            """INSERT INTO calibration_data (confidence_level, domain, total_decisions, correct_count, accuracy_pct)
            VALUES (?, ?, 1, ?, ?)""",
            (confidence, domain, 1 if was_correct else 0, 100.0 if was_correct else 0.0),
        )

    conn.commit()
    conn.close()


def migrate_existing_decisions():
    """Migrate decisions from the old 'decisions' table to decisions_journal."""
    init_decisions_journal()
    conn = get_connection()

    # Check if old decisions table exists
    tables = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'decisions'
        """
    ).fetchone()
    if not tables:
        conn.close()
        return 0

    # Get old decisions not already in journal
    old = conn.execute("""
        SELECT d.* FROM decisions d
        WHERE d.text NOT IN (SELECT text FROM decisions_journal)
    """).fetchall()

    count = 0
    for d in old:
        conn.execute(
            """INSERT INTO decisions_journal (transcript_id, text, made_by, reasoning, confidence, domain, project_name, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'meeting')""",
            (d["transcript_id"], d["text"], d["made_by"], d["context"], 7, "work", d["project"]),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"[Decisions] Migrated {count} decisions to journal")
    return count
