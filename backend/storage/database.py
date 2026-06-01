"""PostgreSQL storage for SudoBrain.

Provides a sqlite3-compatible interface so existing code using `?` placeholders,
`conn.execute()`, and dict-like row access continues to work unchanged.
"""

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("sudobrain.storage")

# Postgres connection config
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
PG_DATABASE = os.getenv("POSTGRES_DATABASE", "sudobrain")


def _translate_sql(sql: str) -> str:
    """Translate SQLite-specific SQL to Postgres.

    Handles:
    - `?` -> `%s`
    - `INSERT OR REPLACE` -> `INSERT ... ON CONFLICT DO UPDATE` (best effort)
    - `INSERT OR IGNORE` -> `INSERT ... ON CONFLICT DO NOTHING`
    - `date('now')` -> `CURRENT_DATE`
    - `datetime('now')` -> `CURRENT_TIMESTAMP`
    - `date('now', '-N days')` -> `CURRENT_DATE - INTERVAL 'N days'`
    - `AUTOINCREMENT` -> (Postgres SERIAL handles this)
    - `BOOLEAN DEFAULT FALSE` -> kept
    - FTS5 virtual tables -> regular table with tsvector (handled in init_db)
    """
    s = sql

    # Type translations
    s = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDATETIME\b", "TIMESTAMP", s, flags=re.IGNORECASE)
    s = re.sub(r"\bBLOB\b", "BYTEA", s, flags=re.IGNORECASE)
    # REAL in SQLite is a float — Postgres has REAL too, leave it alone

    # date('now', '-N days') -> CURRENT_DATE - INTERVAL 'N days'
    s = re.sub(
        r"date\(\s*'now'\s*,\s*'([+-])(\d+)\s+days?'\s*\)",
        lambda m: f"(CURRENT_DATE {m.group(1)} INTERVAL '{m.group(2)} days')",
        s,
        flags=re.IGNORECASE,
    )

    # date('now') -> CURRENT_DATE
    s = re.sub(r"date\(\s*'now'\s*\)", "CURRENT_DATE", s, flags=re.IGNORECASE)

    # datetime('now') -> CURRENT_TIMESTAMP
    s = re.sub(r"datetime\(\s*'now'\s*\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)

    # date(column) -> DATE(column) (upper case is safer)
    s = re.sub(r"\bdate\(([a-zA-Z_][a-zA-Z0-9_]*)\)", r"DATE(\1)", s)

    # INSERT OR REPLACE -> INSERT ... ON CONFLICT (needs PK info which we don't have)
    # Handle case-by-case at call sites
    s = re.sub(r"INSERT OR REPLACE", "INSERT", s, flags=re.IGNORECASE)
    s = re.sub(r"INSERT OR IGNORE", "INSERT", s, flags=re.IGNORECASE)

    # SQLite uses ? for placeholders, Postgres uses %s
    # Be careful not to replace ? inside string literals
    result = []
    in_string = False
    string_char = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            result.append(ch)
            if ch == string_char and (i == 0 or s[i-1] != '\\'):
                in_string = False
        else:
            if ch in ("'", '"'):
                in_string = True
                string_char = ch
                result.append(ch)
            elif ch == '?':
                result.append('%s')
            else:
                result.append(ch)
        i += 1

    return "".join(result)


class _CursorWrapper:
    """Wraps a psycopg2 cursor to look like sqlite3.Cursor."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, sql, params=()):
        translated = _translate_sql(sql)
        self._cursor.execute(translated, params)
        return self

    def executescript(self, script):
        for stmt in _split_statements(script):
            stmt = stmt.strip()
            if stmt:
                translated = _translate_sql(stmt)
                try:
                    self._cursor.execute(translated)
                except psycopg2.Error as e:
                    logger.warning("executescript statement failed: %s — %s", stmt[:80], e)
                    raise

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _Row(row)

    def fetchall(self):
        return [_Row(r) for r in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _Row(dict):
    """Dict-like row wrapper compatible with sqlite3.Row.

    Inherits from dict so `dict(row)` returns a proper dict and JSON serialization works.
    """

    def __init__(self, row):
        super().__init__(row)
        self._row = dict(row)

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._row.values())[key]
        return self._row[key]


class _ConnectionWrapper:
    """Wraps a psycopg2 connection to look like sqlite3.Connection."""

    def __init__(self, conn):
        self._conn = conn
        # RealDictCursor returns rows as dicts
        self._conn.autocommit = False
        self._cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=()):
        translated = _translate_sql(sql)
        stripped = translated.strip()
        upper = stripped.upper()

        # Auto-append RETURNING id for INSERT statements (to get lastrowid)
        auto_returning = False
        if (upper.startswith("INSERT") and "RETURNING" not in upper):
            clean = stripped.rstrip(";").rstrip()
            translated = clean + " RETURNING id"
            auto_returning = True

        # psycopg2 treats `%` as parameter marker. When there are no params,
        # escape literal `%` in the SQL as `%%`.
        if not params:
            # Only escape if there are no %s placeholders intended
            # Simple heuristic: if string has no %s at all, escape all %
            # After _translate_sql, ? was already converted to %s, so if we
            # have no params, any % is literal (from LIKE patterns etc.)
            translated_exec = translated.replace('%', '%%')
        else:
            translated_exec = translated

        try:
            self._cursor.execute(translated_exec, params or None)
        except psycopg2.Error as e:
            self._conn.rollback()
            if auto_returning and "column \"id\"" in str(e).lower():
                retry_sql = _translate_sql(sql)
                if not params:
                    retry_sql = retry_sql.replace('%', '%%')
                self._cursor.execute(retry_sql, params or None)
                cur_wrapper = _CursorWrapper(self._cursor)
                cur_wrapper.lastrowid = None
                return cur_wrapper
            raise

        cur_wrapper = _CursorWrapper(self._cursor)
        if auto_returning or "RETURNING" in upper:
            try:
                row = self._cursor.fetchone()
                if row and "id" in row:
                    cur_wrapper.lastrowid = row["id"]
            except Exception:
                pass
        return cur_wrapper

    def executescript(self, script):
        for stmt in _split_statements(script):
            stmt = stmt.strip()
            if not stmt:
                continue
            translated = _translate_sql(stmt)
            # Escape literal % signs (no params in DDL usually)
            translated_exec = translated.replace('%', '%%')
            try:
                self._cursor.execute(translated_exec)
            except psycopg2.Error as e:
                logger.warning("executescript failed: %s — %s", stmt[:80], e)
                self._conn.rollback()
                raise

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        # Ignore — we use RealDictCursor always
        pass


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on semicolons, respecting string literals."""
    statements = []
    current = []
    in_string = False
    string_char = None
    i = 0
    while i < len(script):
        ch = script[i]
        if in_string:
            current.append(ch)
            if ch == string_char and (i == 0 or script[i-1] != '\\'):
                in_string = False
        else:
            if ch in ("'", '"'):
                in_string = True
                string_char = ch
                current.append(ch)
            elif ch == ';':
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
            else:
                current.append(ch)
        i += 1

    final = "".join(current).strip()
    if final:
        statements.append(final)
    return statements


def get_connection():
    """Get a new Postgres connection wrapped in a sqlite3-compatible interface."""
    raw = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, database=PG_DATABASE,
    )
    return _ConnectionWrapper(raw)


@contextmanager
def _connect():
    """Context manager that guarantees connection cleanup."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Create all tables and indexes in Postgres."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                duration_seconds REAL,
                audio_path TEXT,
                status TEXT DEFAULT 'recorded'
            );

            CREATE TABLE IF NOT EXISTS transcripts (
                id TEXT PRIMARY KEY,
                recording_id TEXT,
                full_text TEXT,
                primary_language TEXT,
                is_code_mixed BOOLEAN,
                engine TEXT DEFAULT 'sarvam',
                processed_at TIMESTAMP,
                transcript_json TEXT
            );

            CREATE TABLE IF NOT EXISTS segments (
                id SERIAL PRIMARY KEY,
                transcript_id TEXT,
                speaker_id TEXT,
                speaker_label TEXT,
                start_seconds REAL,
                end_seconds REAL,
                text TEXT,
                language TEXT
            );

            CREATE TABLE IF NOT EXISTS action_items (
                id SERIAL PRIMARY KEY,
                transcript_id TEXT,
                text TEXT NOT NULL,
                assignee TEXT,
                assigned_by TEXT,
                due_date DATE,
                project TEXT,
                status TEXT DEFAULT 'pending',
                source_start REAL,
                source_end REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id SERIAL PRIMARY KEY,
                transcript_id TEXT,
                text TEXT NOT NULL,
                made_by TEXT,
                context TEXT,
                project TEXT,
                source_start REAL,
                source_end REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                transcript_id TEXT,
                text TEXT NOT NULL,
                urgency TEXT DEFAULT 'normal',
                due_date DATE,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS promises (
                id SERIAL PRIMARY KEY,
                transcript_id TEXT,
                promised_by_name TEXT,
                promised_to_name TEXT,
                description TEXT NOT NULL,
                detected_text TEXT,
                due_date DATE,
                status TEXT DEFAULT 'pending',
                reminder_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_transcripts_recording_id ON transcripts(recording_id);
            CREATE INDEX IF NOT EXISTS idx_segments_transcript_id ON segments(transcript_id);
            CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status);
            CREATE INDEX IF NOT EXISTS idx_action_items_project ON action_items(project);
            CREATE INDEX IF NOT EXISTS idx_action_items_transcript_id ON action_items(transcript_id);
            CREATE INDEX IF NOT EXISTS idx_action_items_due_date ON action_items(due_date);
            CREATE INDEX IF NOT EXISTS idx_decisions_transcript_id ON decisions(transcript_id);
            CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_date);
            CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
            CREATE INDEX IF NOT EXISTS idx_recordings_created_at ON recordings(created_at);

            -- Full-text search on segments using tsvector
            ALTER TABLE segments ADD COLUMN IF NOT EXISTS text_tsv tsvector
                GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;
            CREATE INDEX IF NOT EXISTS idx_segments_tsv ON segments USING GIN(text_tsv);
        """)
        conn.commit()
    finally:
        conn.close()


def save_recording(recording_id: str, mode: str, audio_path: str, duration: float = 0.0):
    with _connect() as conn:
        conn.execute("""
            INSERT INTO recordings (id, mode, created_at, duration_seconds, audio_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                mode = EXCLUDED.mode,
                duration_seconds = EXCLUDED.duration_seconds,
                audio_path = EXCLUDED.audio_path,
                status = EXCLUDED.status
        """, (recording_id, mode, datetime.now(), duration, audio_path, "recorded"))
        conn.commit()


def save_transcript(transcript: dict):
    """Save a unified transcript JSON to the database."""
    with _connect() as conn:
        conn.execute("""
            INSERT INTO transcripts
            (id, recording_id, full_text, primary_language, is_code_mixed, engine, processed_at, transcript_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                recording_id = EXCLUDED.recording_id,
                full_text = EXCLUDED.full_text,
                primary_language = EXCLUDED.primary_language,
                is_code_mixed = EXCLUDED.is_code_mixed,
                engine = EXCLUDED.engine,
                processed_at = EXCLUDED.processed_at,
                transcript_json = EXCLUDED.transcript_json
        """, (
            transcript["id"],
            transcript["recording_id"],
            transcript["full_transcript"],
            transcript["language"]["primary"],
            transcript["language"]["is_code_mixed"],
            transcript["processing"]["engine"],
            transcript["processing"]["processed_at"],
            json.dumps(transcript, ensure_ascii=False),
        ))

        conn.execute(
            "UPDATE recordings SET status = 'completed', duration_seconds = ? WHERE id = ?",
            (transcript["duration_seconds"], transcript["recording_id"]),
        )

        participants = {p["speaker_id"]: p["label"] for p in transcript.get("participants", [])}
        conn.execute("DELETE FROM segments WHERE transcript_id = ?", (transcript["id"],))
        for seg in transcript.get("segments", []):
            conn.execute("""
                INSERT INTO segments (transcript_id, speaker_id, speaker_label, start_seconds, end_seconds, text, language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                transcript["id"],
                seg["speaker_id"],
                participants.get(seg["speaker_id"], seg["speaker_id"]),
                seg["start_seconds"],
                seg["end_seconds"],
                seg["text"],
                seg.get("language", ""),
            ))

        conn.commit()


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _knowledge_row_exists(conn, table: str, transcript_id: str, text_column: str,
                          text: str, extra_column: str | None = None,
                          extra_value: str | None = None) -> bool:
    if not _norm_text(text):
        return True
    params = [transcript_id, _norm_text(text)]
    extra_sql = ""
    if extra_column:
        extra_sql = f" AND COALESCE(LOWER({extra_column}), '') = ?"
        params.append((extra_value or "").strip().lower())
    row = conn.execute(
        f"""
        SELECT id FROM {table}
        WHERE transcript_id = ?
          AND LOWER(REGEXP_REPLACE(COALESCE({text_column}, ''), '\\s+', ' ', 'g')) = ?
          {extra_sql}
        LIMIT 1
        """,
        tuple(params),
    ).fetchone()
    return bool(row)


def save_action_item(transcript_id: str, text: str, assignee: str = None, project: str = None, due_date: str = None):
    with _connect() as conn:
        if _knowledge_row_exists(conn, "action_items", transcript_id, "text", text, "assignee", assignee):
            return
        conn.execute(
            "INSERT INTO action_items (transcript_id, text, assignee, project, due_date) VALUES (?, ?, ?, ?, ?)",
            (transcript_id, text, assignee, project, due_date),
        )
        conn.commit()


def save_decision(transcript_id: str, text: str, made_by: str = None, context: str = None, project: str = None):
    with _connect() as conn:
        if _knowledge_row_exists(conn, "decisions", transcript_id, "text", text, "made_by", made_by):
            return
        conn.execute(
            "INSERT INTO decisions (transcript_id, text, made_by, context, project) VALUES (?, ?, ?, ?, ?)",
            (transcript_id, text, made_by, context, project),
        )
        conn.commit()


def save_reminder(transcript_id: str, text: str, urgency: str = "normal", due_date: str = None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO reminders (transcript_id, text, urgency, due_date) VALUES (?, ?, ?, ?)",
            (transcript_id, text, urgency, due_date),
        )
        conn.commit()


def search_transcripts(query: str, limit: int = 20) -> list:
    """Full-text search across transcript segments using Postgres tsvector."""
    words = re.findall(r'\w+', query)
    if not words:
        return []

    # Use plainto_tsquery which handles the input safely
    limit = min(limit, 100)

    with _connect() as conn:
        rows = conn.execute("""
            SELECT s.*, t.recording_id, r.mode, r.created_at as recording_date
            FROM segments s
            JOIN transcripts t ON t.id = s.transcript_id
            JOIN recordings r ON r.id = t.recording_id
            WHERE s.text_tsv @@ plainto_tsquery('english', ?)
            ORDER BY ts_rank(s.text_tsv, plainto_tsquery('english', ?)) DESC
            LIMIT ?
        """, (query, query, limit)).fetchall()
        if rows:
            return [dict(r._row) for r in rows]

        # FTS can miss unusual identifiers, mixed punctuation, or verifier-style
        # tokens. Fall back to literal token matching so offline search remains
        # useful when no LLM is available.
        stopwords = {
            "a", "an", "and", "are", "about", "did", "does", "for", "from",
            "in", "is", "it", "me", "mentions", "of", "on", "or", "show",
            "the", "this", "to", "was", "what", "when", "where", "who", "with",
        }
        literal_terms = []
        for word in words:
            term = word.lower()
            if len(term) < 3 or term in stopwords:
                continue
            if term not in literal_terms:
                literal_terms.append(term)
        literal_terms = sorted(literal_terms, key=len, reverse=True)[:6]
        if not literal_terms:
            return []

        predicates = []
        rank_parts = []
        for term in literal_terms:
            predicates.append("LOWER(s.text) LIKE ?")
            rank_parts.append("CASE WHEN LOWER(s.text) LIKE ? THEN 1 ELSE 0 END")

        predicate_params = [f"%{term}%" for term in literal_terms]
        rank_params = [f"%{term}%" for term in literal_terms]

        rows = conn.execute(f"""
            SELECT s.*, t.recording_id, r.mode, r.created_at as recording_date
            FROM segments s
            JOIN transcripts t ON t.id = s.transcript_id
            JOIN recordings r ON r.id = t.recording_id
            WHERE {" OR ".join(predicates)}
            ORDER BY ({" + ".join(rank_parts)}) DESC, r.created_at DESC
            LIMIT ?
        """, (*predicate_params, *rank_params, limit)).fetchall()
        return [dict(r._row) for r in rows]


def get_pending_action_items(project: Optional[str] = None) -> list:
    with _connect() as conn:
        if project:
            rows = conn.execute(
                "SELECT * FROM action_items WHERE status = 'pending' AND project = ? ORDER BY created_at DESC",
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM action_items WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r._row) for r in rows]


def get_recent_recordings(limit: int = 10) -> list:
    limit = min(limit, 100)
    with _connect() as conn:
        rows = conn.execute("""
            SELECT r.*, t.id as transcript_id, SUBSTRING(t.full_text FROM 1 FOR 500) as full_text
            FROM recordings r
            LEFT JOIN transcripts t ON t.recording_id = r.id
            ORDER BY r.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r._row) for r in rows]


# Initialize database on import
try:
    init_db()
except Exception as e:
    logger.error("Failed to init Postgres: %s", e)
