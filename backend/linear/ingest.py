"""Linear ingestion — store issues in Postgres and extract knowledge."""

import json
import logging
import hashlib
from datetime import datetime
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.linear.ingest")


def init_linear_tables():
    """Create Linear storage tables."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS linear_issues (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                state_name TEXT,
                state_type TEXT,
                priority INTEGER,
                priority_label TEXT,
                assignee_name TEXT,
                assignee_email TEXT,
                creator_name TEXT,
                team_name TEXT,
                project_name TEXT,
                labels TEXT,
                due_date DATE,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                url TEXT,
                comments_json TEXT,
                extracted BOOLEAN DEFAULT FALSE
            );
            ALTER TABLE linear_issues ALTER COLUMN created_at TYPE TIMESTAMPTZ USING (created_at AT TIME ZONE 'UTC');
            ALTER TABLE linear_issues ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING (updated_at AT TIME ZONE 'UTC');
            ALTER TABLE linear_issues ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING (completed_at AT TIME ZONE 'UTC');

            CREATE TABLE IF NOT EXISTS linear_projects (
                id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                state TEXT,
                start_date DATE,
                target_date DATE,
                progress REAL,
                lead_name TEXT,
                lead_email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS linear_members (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                display_name TEXT,
                person_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_linear_state ON linear_issues(state_type);
            CREATE INDEX IF NOT EXISTS idx_linear_assignee ON linear_issues(assignee_email);
            CREATE INDEX IF NOT EXISTS idx_linear_project ON linear_issues(project_name);
            CREATE INDEX IF NOT EXISTS idx_linear_due ON linear_issues(due_date);
            CREATE INDEX IF NOT EXISTS idx_linear_extracted ON linear_issues(extracted);
        """)
        conn.commit()
    finally:
        conn.close()


def store_issue(issue: dict) -> str:
    """Store a Linear issue."""
    init_linear_tables()
    conn = get_connection()
    try:
        issue_id = issue.get("id")
        if not issue_id:
            return ""

        state = issue.get("state") or {}
        assignee = issue.get("assignee") or {}
        creator = issue.get("creator") or {}
        team = issue.get("team") or {}
        project = issue.get("project") or {}
        labels = [l.get("name", "") for l in (issue.get("labels") or {}).get("nodes", [])]
        comments = (issue.get("comments") or {}).get("nodes", [])

        conn.execute("""
            INSERT INTO linear_issues
            (id, title, description, state_name, state_type, priority, priority_label,
             assignee_name, assignee_email, creator_name, team_name, project_name,
             labels, due_date, completed_at, created_at, updated_at, url, comments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                state_name = EXCLUDED.state_name,
                state_type = EXCLUDED.state_type,
                priority = EXCLUDED.priority,
                assignee_name = EXCLUDED.assignee_name,
                assignee_email = EXCLUDED.assignee_email,
                project_name = EXCLUDED.project_name,
                due_date = EXCLUDED.due_date,
                completed_at = EXCLUDED.completed_at,
                updated_at = EXCLUDED.updated_at,
                comments_json = EXCLUDED.comments_json,
                extracted = FALSE
        """, (
            issue_id,
            issue.get("title", ""),
            (issue.get("description") or "")[:2000],
            state.get("name", ""),
            state.get("type", ""),
            issue.get("priority", 0),
            issue.get("priorityLabel", ""),
            assignee.get("name", ""),
            assignee.get("email", ""),
            creator.get("name", ""),
            team.get("name", ""),
            project.get("name", ""),
            json.dumps(labels),
            issue.get("dueDate"),
            issue.get("completedAt"),
            issue.get("createdAt"),
            issue.get("updatedAt"),
            issue.get("url", ""),
            json.dumps(comments),
        ))
        conn.commit()
        return issue_id
    finally:
        conn.close()


def store_project(project: dict):
    """Store a Linear project."""
    init_linear_tables()
    conn = get_connection()
    try:
        lead = project.get("lead") or {}
        conn.execute("""
            INSERT INTO linear_projects
            (id, name, description, state, start_date, target_date, progress, lead_name, lead_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                state = EXCLUDED.state,
                target_date = EXCLUDED.target_date,
                progress = EXCLUDED.progress,
                lead_name = EXCLUDED.lead_name
        """, (
            project["id"],
            project.get("name", ""),
            (project.get("description") or "")[:1000],
            project.get("state", ""),
            project.get("startDate"),
            project.get("targetDate"),
            project.get("progress", 0),
            lead.get("name", ""),
            lead.get("email", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def store_member(member: dict):
    """Store a Linear member and link to people graph."""
    init_linear_tables()

    # Try to link to existing person by email
    person_id = None
    email = member.get("email", "").strip().lower()
    if email:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM people WHERE LOWER(email) = ?", (email,)
            ).fetchone()
            if row:
                person_id = row["id"]
            else:
                from backend.people.graph import get_or_create_person
                name = member.get("name") or member.get("displayName") or email
                person_id = get_or_create_person(name, email=email)
        finally:
            conn.close()

    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO linear_members (id, name, email, display_name, person_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                person_id = COALESCE(EXCLUDED.person_id, linear_members.person_id)
        """, (
            member["id"],
            member.get("name", ""),
            email or None,
            member.get("displayName", ""),
            person_id,
        ))
        conn.commit()
    finally:
        conn.close()


def extract_from_issues(batch_size: int = 30) -> int:
    """Extract knowledge from unextracted Linear issues."""
    from backend.ai.local_llm_engine import extract_knowledge
    from backend.graph.neo4j_client import ingest_knowledge
    from backend.storage import database as db

    init_linear_tables()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, title, description, state_name, state_type,
                   assignee_name, assignee_email, creator_name,
                   team_name, project_name, labels, due_date, comments_json
            FROM linear_issues
            WHERE extracted = FALSE
              AND state_type NOT IN ('cancelled')
            ORDER BY updated_at DESC
            LIMIT ?
        """, (batch_size * 5,)).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    logger.info("Extracting from %d Linear issues", len(rows))
    processed = 0

    # Process in batches
    for i in range(0, len(rows), batch_size):
        batch = [dict(r._row) if hasattr(r, '_row') else dict(r) for r in rows[i:i + batch_size]]
        batch_text = _format_issues_for_extraction(batch)

        if len(batch_text) < 50:
            continue

        try:
            knowledge = extract_knowledge(batch_text)
            if knowledge:
                batch_key = hashlib.sha1(
                    "|".join(sorted(r["id"] for r in batch)).encode("utf-8")
                ).hexdigest()[:12]
                synthetic_tid = f"linear_batch_{batch_key}"
                rec_id = f"rec_{synthetic_tid}"
                db.save_recording(rec_id, "linear", f"linear://issues/{synthetic_tid}", 0)

                transcript_stub = {
                    "id": synthetic_tid,
                    "recording_id": rec_id,
                    "source": "linear",
                    "created_at": datetime.now().isoformat(),
                    "duration_seconds": 0,
                    "language": {"primary": "en", "detected": ["en"], "is_code_mixed": False},
                    "participants": [],
                    "segments": [{"speaker_id": "linear", "start_seconds": 0,
                                  "end_seconds": 0, "text": batch_text[:3000], "language": "en"}],
                    "full_transcript": batch_text,
                    "processing": {"engine": "linear", "model": "n/a",
                                   "processed_at": datetime.now().isoformat(),
                                   "audio_preprocessing": []},
                }
                db.save_transcript(transcript_stub)

                for item in knowledge.get("action_items", []):
                    db.save_action_item(
                        transcript_id=synthetic_tid,
                        text=item.get("text", ""),
                        assignee=item.get("assignee"),
                        project=knowledge.get("project"),
                        due_date=item.get("due_date"),
                    )
                for item in knowledge.get("decisions", []):
                    db.save_decision(
                        transcript_id=synthetic_tid,
                        text=item.get("text", ""),
                        made_by=item.get("made_by"),
                        context=item.get("context"),
                        project=knowledge.get("project"),
                    )

                try:
                    participants = list({r.get("assignee_name", "") for r in batch if r.get("assignee_name")})
                    ingest_knowledge(knowledge, synthetic_tid, participants=participants)
                except Exception as e:
                    logger.debug("Graph ingestion skipped: %s", e)

            processed += len(batch)
        except Exception as e:
            logger.warning("Linear batch extraction failed: %s", e)

        # Mark batch as extracted
        ids = [r["id"] for r in batch]
        conn = get_connection()
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE linear_issues SET extracted = TRUE WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        finally:
            conn.close()

    return processed


def _format_issues_for_extraction(issues: list[dict]) -> str:
    """Format Linear issues as readable text for local reasoning engine extraction."""
    lines = ["[Linear Issues — Project Tasks and Decisions]\n"]

    for issue in issues:
        title = issue.get("title", "")
        state = issue.get("state_name", "")
        assignee = issue.get("assignee_name", "") or "unassigned"
        project = issue.get("project_name", "") or issue.get("team_name", "")
        due = issue.get("due_date", "")
        desc = (issue.get("description") or "").strip()[:500]
        priority = issue.get("priority_label", "")

        line = f"[{state}][{priority}] {title}"
        if project:
            line += f" — {project}"
        line += f" (assigned to: {assignee}"
        if due:
            line += f", due: {due}"
        line += ")"
        lines.append(line)

        if desc:
            lines.append(f"  Description: {desc}")

        # Include comments
        try:
            comments = json.loads(issue.get("comments_json") or "[]")
            for c in comments[:3]:
                user = (c.get("user") or {}).get("name", "?")
                body = (c.get("body") or "").strip()[:200]
                if body:
                    lines.append(f"  Comment by {user}: {body}")
        except Exception:
            pass

        lines.append("")

    return "\n".join(lines)


def get_issue_stats() -> dict:
    """Get Linear sync statistics."""
    init_linear_tables()
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM linear_issues").fetchone()["c"]
        extracted = conn.execute("SELECT COUNT(*) as c FROM linear_issues WHERE extracted = TRUE").fetchone()["c"]
        by_state = conn.execute("""
            SELECT state_name, COUNT(*) as c FROM linear_issues
            GROUP BY state_name ORDER BY c DESC
        """).fetchall()
        projects = conn.execute("SELECT COUNT(DISTINCT project_name) as c FROM linear_issues WHERE project_name != ''").fetchone()["c"]
        return {
            "total_issues": total,
            "extracted": extracted,
            "projects": projects,
            "by_state": {r["state_name"]: r["c"] for r in by_state},
        }
    finally:
        conn.close()
