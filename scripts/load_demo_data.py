#!/usr/bin/env python3
"""Seed SudoBrain with synthetic demo data.

The dataset is intentionally fake and public-safe. It exercises meetings,
transcripts, Slack-like messages, Gmail-like messages, projects, tasks,
decisions, promises, and people so a new user can explore the app without
private credentials.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from backend.storage import database as db


NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


PEOPLE = [
    ("Alex Rivera", "alex@example.test", "Product Lead", "Northstar Robotics"),
    ("Maya Chen", "maya@example.test", "Engineering Lead", "Northstar Robotics"),
    ("Jordan Patel", "jordan@example.test", "Customer Success", "Northstar Robotics"),
    ("Sam Okafor", "sam@example.test", "Design", "Northstar Robotics"),
    ("Taylor Brooks", "taylor@example.test", "Finance", "Northstar Robotics"),
]


PROJECTS = [
    ("Atlas Launch", "Public beta launch for the Atlas customer workspace", "active"),
    ("Beacon Reliability", "Reduce alert fatigue and improve incident handoffs", "active"),
    ("Customer Pulse", "Track expansion risk from meetings and email signals", "active"),
]


MEETINGS = [
    {
        "recording_id": "demo-rec-atlas-kickoff",
        "transcript_id": "demo-tr-atlas-kickoff",
        "mode": "meeting",
        "created_at": "2026-05-28T10:00:00+00:00",
        "title": "Atlas beta launch kickoff",
        "segments": [
            ("S1", "Alex Rivera", 0.0, 8.0, "We will keep the Atlas launch local-first by default and make cloud model providers opt-in."),
            ("S2", "Maya Chen", 8.0, 16.0, "I will add source citation cards to chat answers before the beta readout on June 7."),
            ("S3", "Sam Okafor", 16.0, 24.0, "The onboarding flow should show Postgres, Neo4j, Chroma, Ollama, Slack, Gmail, Fathom, Linear, and Calendar health."),
            ("S4", "Jordan Patel", 24.0, 32.0, "Decision: the public demo will use synthetic workspace data and no private credentials."),
        ],
        "actions": [
            ("Add source citation cards to chat answers", "Maya Chen", "Atlas Launch", "2026-06-07"),
            ("Prepare synthetic demo script for launch walkthrough", "Jordan Patel", "Atlas Launch", "2026-06-05"),
        ],
        "decisions": [
            ("Public demo uses synthetic workspace data only", "Jordan Patel", "Atlas Launch"),
            ("Cloud model providers stay opt-in", "Alex Rivera", "Atlas Launch"),
        ],
        "promises": [
            ("Maya Chen", "Alex Rivera", "Add source citation cards to chat answers before beta readout", "2026-06-07"),
        ],
    },
    {
        "recording_id": "demo-rec-beacon-review",
        "transcript_id": "demo-tr-beacon-review",
        "mode": "meeting",
        "created_at": "2026-05-30T15:00:00+00:00",
        "title": "Beacon reliability review",
        "segments": [
            ("S1", "Maya Chen", 0.0, 9.0, "The recurring problem is noisy escalation during low-severity incidents."),
            ("S2", "Taylor Brooks", 9.0, 18.0, "We should measure meeting ROI for the incident review series and archive low-value repeats."),
            ("S3", "Alex Rivera", 18.0, 27.0, "Decision: create an approval step before any workflow sends external notifications."),
            ("S4", "Maya Chen", 27.0, 36.0, "I will publish a workflow template for stale decision reviews by June 10."),
        ],
        "actions": [
            ("Create approval gate for outbound workflow notifications", "Maya Chen", "Beacon Reliability", "2026-06-10"),
            ("Summarize meeting ROI trend for incident reviews", "Taylor Brooks", "Beacon Reliability", "2026-06-12"),
        ],
        "decisions": [
            ("External notifications require approval steps", "Alex Rivera", "Beacon Reliability"),
        ],
        "promises": [
            ("Maya Chen", "Taylor Brooks", "Publish stale decision review workflow template", "2026-06-10"),
        ],
    },
]


SLACK_MESSAGES = [
    ("CDEMOATLAS", "atlas-launch", "1717056000.000100", "Maya Chen", "Citation card PR is ready for review. It links each answer back to transcript, task, decision, or promise records."),
    ("CDEMOATLAS", "atlas-launch", "1717059600.000200", "Sam Okafor", "Onboarding mockup now groups service health, integrations, privacy mode, and demo data status."),
    ("CDEMOBEACON", "beacon-reliability", "1717142400.000300", "Taylor Brooks", "Beacon risk digest should include stale decisions, blocked tasks, and customer pulse changes."),
]


GMAIL_MESSAGES = [
    (
        "demo-gmail-atlas-readout",
        "demo-thread-atlas",
        "Atlas beta readout prep",
        "Jordan Patel <jordan@example.test>",
        "Alex Rivera <alex@example.test>, Maya Chen <maya@example.test>",
        "Can we show the demo workspace, source citations, and Markdown export in the public walkthrough?",
    ),
    (
        "demo-gmail-customer-pulse",
        "demo-thread-pulse",
        "Customer pulse risk signals",
        "Taylor Brooks <taylor@example.test>",
        "Jordan Patel <jordan@example.test>",
        "The synthetic customer account should show one expansion risk and one recovered relationship.",
    ),
]


def execute(conn, sql: str, params: tuple = ()) -> None:
    conn.execute(sql, params)


def init_optional_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS people (
            id SERIAL PRIMARY KEY,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS slack_channels (
            id TEXT PRIMARY KEY,
            name TEXT,
            topic TEXT,
            purpose TEXT,
            is_private BOOLEAN DEFAULT FALSE,
            is_dm BOOLEAN DEFAULT FALSE,
            is_archived BOOLEAN DEFAULT FALSE,
            member_count INTEGER DEFAULT 0,
            last_synced_at TIMESTAMP,
            sync_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS slack_messages (
            id SERIAL PRIMARY KEY,
            ts TEXT NOT NULL,
            message_at TIMESTAMPTZ,
            channel_id TEXT NOT NULL,
            user_id TEXT,
            user_name TEXT,
            text TEXT,
            thread_ts TEXT,
            is_thread_parent BOOLEAN DEFAULT FALSE,
            reply_count INTEGER DEFAULT 0,
            reaction_count INTEGER DEFAULT 0,
            mention_users TEXT,
            is_bot_message BOOLEAN DEFAULT FALSE,
            validation_status TEXT DEFAULT 'valid',
            validation_reason TEXT DEFAULT 'demo_seed',
            extracted BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, ts)
        );

        CREATE TABLE IF NOT EXISTS gmail_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            subject TEXT,
            from_email TEXT,
            from_name TEXT,
            to_emails TEXT,
            date TIMESTAMPTZ,
            snippet TEXT,
            body TEXT,
            labels TEXT,
            validation_status TEXT DEFAULT 'valid',
            validation_reason TEXT DEFAULT 'demo_seed',
            extracted BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def clear_demo_data(conn) -> None:
    for table, column in [
        ("segments", "transcript_id"),
        ("action_items", "transcript_id"),
        ("decisions", "transcript_id"),
        ("promises", "transcript_id"),
        ("transcripts", "id"),
        ("recordings", "id"),
    ]:
        execute(conn, f"DELETE FROM {table} WHERE {column} LIKE 'demo-%'")
    execute(conn, "DELETE FROM projects WHERE name IN (?, ?, ?)", tuple(p[0] for p in PROJECTS))
    execute(conn, "DELETE FROM people WHERE email LIKE '%@example.test'")
    execute(conn, "DELETE FROM slack_messages WHERE channel_id LIKE 'CDEMO%'")
    execute(conn, "DELETE FROM slack_channels WHERE id LIKE 'CDEMO%'")
    execute(conn, "DELETE FROM gmail_messages WHERE id LIKE 'demo-%'")


def seed_people(conn) -> None:
    for name, email, role, org in PEOPLE:
        execute(
            conn,
            """
            INSERT INTO people (name, email, role, organization, first_interaction, last_interaction, total_interactions, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, role, org, "2026-05-28", "2026-06-01", 3, "Synthetic demo profile"),
        )


def seed_projects(conn) -> None:
    for name, description, status in PROJECTS:
        execute(
            conn,
            """
            INSERT INTO projects (name, description, status)
            VALUES (?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description, status = EXCLUDED.status
            """,
            (name, description, status),
        )


def seed_meetings(conn) -> None:
    for meeting in MEETINGS:
        full_text = "\n".join(segment[4] for segment in meeting["segments"])
        execute(
            conn,
            """
            INSERT INTO recordings (id, mode, created_at, duration_seconds, audio_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status
            """,
            (meeting["recording_id"], meeting["mode"], meeting["created_at"], 36.0, "demo://synthetic", "completed"),
        )
        execute(
            conn,
            """
            INSERT INTO transcripts (id, recording_id, full_text, primary_language, is_code_mixed, engine, processed_at, transcript_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET full_text = EXCLUDED.full_text, transcript_json = EXCLUDED.transcript_json
            """,
            (
                meeting["transcript_id"],
                meeting["recording_id"],
                full_text,
                "en",
                False,
                "demo",
                meeting["created_at"],
                json.dumps({"title": meeting["title"], "segments": meeting["segments"]}),
            ),
        )
        for speaker_id, speaker, start, end, text in meeting["segments"]:
            execute(
                conn,
                """
                INSERT INTO segments (transcript_id, speaker_id, speaker_label, start_seconds, end_seconds, text, language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (meeting["transcript_id"], speaker_id, speaker, start, end, text, "en"),
            )
        for text, assignee, project, due in meeting["actions"]:
            execute(
                conn,
                """
                INSERT INTO action_items (transcript_id, text, assignee, project, due_date, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (meeting["transcript_id"], text, assignee, project, due),
            )
        for text, made_by, project in meeting["decisions"]:
            execute(
                conn,
                """
                INSERT INTO decisions (transcript_id, text, made_by, context, project)
                VALUES (?, ?, ?, ?, ?)
                """,
                (meeting["transcript_id"], text, made_by, meeting["title"], project),
            )
        for by, to, description, due in meeting["promises"]:
            execute(
                conn,
                """
                INSERT INTO promises (transcript_id, promised_by_name, promised_to_name, description, due_date, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (meeting["transcript_id"], by, to, description, due),
            )


def seed_sources(conn) -> None:
    for channel_id, channel_name in [("CDEMOATLAS", "atlas-launch"), ("CDEMOBEACON", "beacon-reliability")]:
        execute(
            conn,
            """
            INSERT INTO slack_channels (id, name, topic, purpose, member_count, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, last_synced_at = EXCLUDED.last_synced_at
            """,
            (channel_id, channel_name, "Synthetic demo channel", "Try SudoBrain without Slack credentials", 5, NOW.isoformat()),
        )
    for channel_id, _, ts, user, text in SLACK_MESSAGES:
        execute(
            conn,
            """
            INSERT INTO slack_messages (channel_id, ts, message_at, user_name, text, validation_status, validation_reason, extracted)
            VALUES (?, ?, to_timestamp(?), ?, ?, 'valid', 'demo_seed', TRUE)
            ON CONFLICT (channel_id, ts) DO UPDATE SET text = EXCLUDED.text, extracted = TRUE
            """,
            (channel_id, ts, float(ts), user, text),
        )
    for msg_id, thread_id, subject, from_field, to_emails, body in GMAIL_MESSAGES:
        from_name = from_field.split("<")[0].strip()
        from_email = from_field.split("<")[1].rstrip(">")
        execute(
            conn,
            """
            INSERT INTO gmail_messages
            (id, thread_id, subject, from_email, from_name, to_emails, date, snippet, body, labels, validation_status, validation_reason, extracted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid', 'demo_seed', TRUE)
            ON CONFLICT (id) DO UPDATE SET subject = EXCLUDED.subject, body = EXCLUDED.body, extracted = TRUE
            """,
            (msg_id, thread_id, subject, from_email, from_name, to_emails, NOW.isoformat(), body[:120], body, "INBOX,DEMO"),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Load public-safe synthetic SudoBrain demo data.")
    parser.add_argument("--keep-existing", action="store_true", help="Keep any existing demo rows instead of replacing them.")
    args = parser.parse_args()

    conn = db.get_connection()
    try:
        init_optional_tables(conn)
        if not args.keep_existing:
            clear_demo_data(conn)
        seed_people(conn)
        seed_projects(conn)
        seed_meetings(conn)
        seed_sources(conn)
        conn.commit()
    finally:
        conn.close()

    print("Loaded SudoBrain synthetic demo workspace.")
    print("Try: curl 'http://127.0.0.1:8420/search?q=Atlas'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
