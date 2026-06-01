"""Source ingestion health audit.

This module is intentionally DB/graph-first: it does not call Gmail, Slack,
Fathom, or any other external source. It reports whether the local knowledge
copy is valid, deduplicated, and graph-aligned.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

from backend.storage.database import get_connection


def collect_source_audit() -> dict:
    """Return an enterprise-style health report for source ingestion."""
    conn = get_connection()
    try:
        counts = _table_counts(conn)
        validation = {
            "slack": _group_counts(
                conn,
                """
                SELECT validation_status, validation_reason, COUNT(*) c
                FROM slack_messages
                GROUP BY validation_status, validation_reason
                ORDER BY c DESC
                """,
                ["validation_status", "validation_reason"],
            ),
            "gmail": _group_counts(
                conn,
                """
                SELECT validation_status, validation_reason, COUNT(*) c
                FROM gmail_messages
                GROUP BY validation_status, validation_reason
                ORDER BY c DESC
                """,
                ["validation_status", "validation_reason"],
            ),
            "gmail_attachments": _group_counts(
                conn,
                """
                SELECT content_kind, file_type, extraction_status, extraction_reason,
                       COUNT(*) c,
                       SUM(CASE WHEN char_count > 0 THEN 1 ELSE 0 END) with_text
                FROM gmail_attachments
                GROUP BY content_kind, file_type, extraction_status, extraction_reason
                ORDER BY content_kind, file_type, extraction_status
                """,
                ["content_kind", "file_type", "extraction_status", "extraction_reason"],
                count_fields=["c", "with_text"],
            ),
        }
        slack_channels = _slack_channel_summary(conn)
        project_context = _project_context_summary(conn)
        duplicates = _duplicate_audit(conn)
        fathom = _fathom_audit(conn)
        source_sync = _latest_source_sync(conn)
    finally:
        conn.close()

    graph = _graph_audit()
    semantic_quality = _semantic_quality_audit()
    issues = _issues(counts, validation, slack_channels, project_context, duplicates, fathom, graph, semantic_quality)

    return {
        "status": "ok" if not issues else "warning",
        "issues": issues,
        "counts": counts,
        "validation": validation,
        "slack_channels": slack_channels,
        "project_context": project_context,
        "duplicates": duplicates,
        "fathom": fathom,
        "graph": graph,
        "semantic_quality": semantic_quality,
        "source_sync": source_sync,
    }


def _table_counts(conn) -> dict:
    tables = [
        "recordings",
        "transcripts",
        "segments",
        "action_items",
        "decisions",
        "promises",
        "slack_messages",
        "gmail_messages",
        "gmail_attachments",
        "projects",
        "project_sources",
        "project_contributors",
    ]
    out = {}
    for table in tables:
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        except Exception:
            out[table] = None
    return out


def _group_counts(conn, sql: str, key_fields: list[str], count_fields: list[str] | None = None) -> list[dict]:
    count_fields = count_fields or ["c"]
    rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        item = {key: row[key] for key in key_fields}
        for field in count_fields:
            item[field] = row[field]
        out.append(item)
    return out


def _slack_channel_summary(conn) -> dict:
    row = conn.execute("""
        SELECT COUNT(*) total,
               COUNT(*) FILTER (WHERE sync_enabled = TRUE AND is_archived = FALSE) enabled,
               COUNT(*) FILTER (WHERE sync_enabled = FALSE AND is_archived = FALSE) ignored,
               COUNT(*) FILTER (WHERE is_archived = TRUE) archived,
               COUNT(*) FILTER (WHERE is_dm = TRUE AND sync_enabled = TRUE AND is_archived = FALSE) enabled_dms,
               COUNT(*) FILTER (WHERE is_dm = TRUE AND sync_enabled = FALSE AND is_archived = FALSE) ignored_dms
        FROM slack_channels
    """).fetchone()
    invalid_rows = conn.execute("""
        SELECT COUNT(*) c
        FROM slack_channels c
        JOIN slack_messages m ON m.channel_id = c.id
        WHERE (c.sync_enabled = FALSE OR c.is_archived = TRUE)
          AND m.validation_status = 'valid'
    """).fetchone()["c"]
    return {
        "total": row["total"],
        "enabled": row["enabled"],
        "ignored": row["ignored"],
        "archived": row["archived"],
        "enabled_dms": row["enabled_dms"],
        "ignored_dms": row["ignored_dms"],
        "valid_messages_in_ignored_scope": invalid_rows,
    }


def _project_context_summary(conn) -> dict:
    source_rows = conn.execute("""
        SELECT p.name, COUNT(ps.id) sources
        FROM projects p
        LEFT JOIN project_sources ps ON ps.project_id = p.id
        GROUP BY p.id, p.name
        ORDER BY p.name
    """).fetchall()
    contributor_rows = conn.execute("""
        SELECT p.name, COUNT(pc.id) contributors
        FROM projects p
        LEFT JOIN project_contributors pc ON pc.project_id = p.id
        GROUP BY p.id, p.name
        ORDER BY p.name
    """).fetchall()
    sources = {row["name"]: row["sources"] for row in source_rows}
    contributors = {row["name"]: row["contributors"] for row in contributor_rows}
    required = [
        item.strip()
        for item in os.getenv("SUDOBRAIN_REQUIRED_PROJECTS", "").split(",")
        if item.strip()
    ]
    return {
        "projects": len(sources),
        "source_links": sum(sources.values()),
        "contributors": sum(contributors.values()),
        "required_alias_projects": {
            name: {
                "present": name in sources,
                "source_links": sources.get(name, 0),
                "contributors": contributors.get(name, 0),
            }
            for name in required
        },
    }


def _duplicate_audit(conn) -> dict:
    queries = {
        "duplicate_recording_audio_paths": """
            SELECT COUNT(*) c FROM (
                SELECT audio_path
                FROM recordings
                WHERE audio_path IS NOT NULL AND audio_path <> ''
                GROUP BY audio_path
                HAVING COUNT(*) > 1
            ) x
        """,
        "orphan_recordings": """
            SELECT COUNT(*) c
            FROM recordings r
            WHERE NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.recording_id = r.id)
        """,
        "duplicate_segments": """
            SELECT COUNT(*) c FROM (
                SELECT transcript_id, speaker_id, start_seconds, end_seconds, text
                FROM segments
                GROUP BY transcript_id, speaker_id, start_seconds, end_seconds, text
                HAVING COUNT(*) > 1
            ) x
        """,
        "duplicate_actions": """
            SELECT COUNT(*) c FROM (
                SELECT transcript_id,
                       LOWER(REGEXP_REPLACE(COALESCE(text, ''), '\\s+', ' ', 'g')) text_norm,
                       COALESCE(LOWER(assignee), '') assignee
                FROM action_items
                GROUP BY transcript_id, text_norm, assignee
                HAVING COUNT(*) > 1
            ) x
        """,
        "duplicate_decisions": """
            SELECT COUNT(*) c FROM (
                SELECT transcript_id,
                       LOWER(REGEXP_REPLACE(COALESCE(text, ''), '\\s+', ' ', 'g')) text_norm,
                       COALESCE(LOWER(made_by), '') made_by
                FROM decisions
                GROUP BY transcript_id, text_norm, made_by
                HAVING COUNT(*) > 1
            ) x
        """,
        "duplicate_promises": """
            SELECT COUNT(*) c FROM (
                SELECT transcript_id,
                       LOWER(REGEXP_REPLACE(COALESCE(description, ''), '\\s+', ' ', 'g')) text_norm,
                       COALESCE(LOWER(promised_by_name), '') by_name,
                       COALESCE(LOWER(promised_to_name), '') to_name
                FROM promises
                GROUP BY transcript_id, text_norm, by_name, to_name
                HAVING COUNT(*) > 1
            ) x
        """,
        "slack_unvalidated": """
            SELECT COUNT(*) c
            FROM slack_messages
            WHERE validation_status IS NULL
               OR validation_reason IS NULL
               OR validation_status = 'unvalidated'
        """,
        "gmail_unvalidated": """
            SELECT COUNT(*) c
            FROM gmail_messages
            WHERE validation_status IS NULL
               OR validation_reason IS NULL
               OR validation_status = 'unvalidated'
        """,
        "gmail_pending_extraction": "SELECT COUNT(*) c FROM gmail_messages WHERE extracted = FALSE",
    }
    return {name: conn.execute(sql).fetchone()["c"] for name, sql in queries.items()}


def _fathom_audit(conn) -> dict:
    rows = conn.execute("SELECT id, transcript_json FROM transcripts").fetchall()
    by_fathom_id = defaultdict(list)
    for row in rows:
        try:
            payload = json.loads(row["transcript_json"] or "{}")
        except Exception:
            continue
        fathom_id = (payload.get("fathom") or {}).get("fathom_recording_id")
        engine = (payload.get("processing") or {}).get("engine")
        source = payload.get("source")
        if fathom_id and (engine == "sarvam" or source == "fathom_meeting"):
            by_fathom_id[str(fathom_id)].append(row["id"])
    duplicates = {fid: tids for fid, tids in by_fathom_id.items() if len(tids) > 1}
    return {
        "sarvam_processed_recordings": len(by_fathom_id),
        "duplicate_fathom_recording_ids": duplicates,
    }


def _latest_source_sync(conn) -> list[dict]:
    try:
        rows = conn.execute("""
            SELECT DISTINCT ON (source) source, status, detail, completed_at
            FROM source_sync_log
            ORDER BY source, completed_at DESC
        """).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _graph_audit() -> dict:
    try:
        from backend.graph.neo4j_client import get_driver, graph_stats

        driver = get_driver()
        if not driver:
            return {"available": False}
        stats = graph_stats()
        duplicates = {}
        stale = {}
        conn = get_connection()
        try:
            transcript_ids = {row["id"] for row in conn.execute("SELECT id FROM transcripts").fetchall()}
        finally:
            conn.close()

        with driver.session() as session:
            for label, prop in [
                ("Person", "name"),
                ("Project", "name"),
                ("ActionItem", "id"),
                ("Decision", "id"),
                ("Promise", "id"),
                ("Meeting", "transcript_id"),
            ]:
                rows = session.run(
                    f"""
                    MATCH (n:{label})
                    WITH toLower(toString(n.{prop})) AS key, COUNT(*) AS c
                    WHERE key IS NOT NULL AND key <> '' AND c > 1
                    RETURN key, c
                    LIMIT 20
                    """
                ).data()
                duplicates[label] = rows
            for label in ["Meeting", "ActionItem", "Decision", "Promise"]:
                rows = session.run(
                    f"""
                    MATCH (n:{label})
                    WHERE n.transcript_id IS NOT NULL
                    RETURN n.transcript_id AS transcript_id, COUNT(*) AS c
                    """
                ).data()
                stale[label] = sum(row["c"] for row in rows if row["transcript_id"] not in transcript_ids)
        return {**stats, "duplicates": duplicates, "stale_transcript_nodes": stale}
    except Exception as e:
        return {"available": False, "error": str(e)}


def _semantic_quality_audit() -> dict:
    try:
        from backend.knowledge_quality import collect_knowledge_quality_audit

        return collect_knowledge_quality_audit()
    except Exception as e:
        return {"status": "warning", "issues": ["semantic_quality_error"], "error": str(e)}


def _issues(counts, validation, slack_channels, project_context, duplicates, fathom, graph, semantic_quality) -> list[str]:
    issues = []
    for key, value in duplicates.items():
        if value:
            issues.append(f"{key}:{value}")
    if slack_channels.get("valid_messages_in_ignored_scope"):
        issues.append("slack_valid_messages_in_ignored_scope")
    if any(row.get("validation_status") in (None, "unvalidated") for row in validation["slack"]):
        issues.append("slack_unvalidated_messages")
    if any(row.get("validation_status") in (None, "unvalidated") for row in validation["gmail"]):
        issues.append("gmail_unvalidated_messages")
    for name, status in project_context["required_alias_projects"].items():
        if not status["present"]:
            issues.append(f"missing_project_context:{name}")
    if fathom["duplicate_fathom_recording_ids"]:
        issues.append("duplicate_fathom_recording_ids")
    if semantic_quality.get("status") != "ok":
        for issue in semantic_quality.get("issues") or ["semantic_quality_warning"]:
            issues.append(f"semantic_{issue}")
    if not graph.get("available"):
        issues.append("neo4j_unavailable")
    else:
        graph_dups = graph.get("duplicates", {})
        for label, rows in graph_dups.items():
            if rows:
                issues.append(f"graph_duplicate_{label}")
        stale = graph.get("stale_transcript_nodes", {})
        for label, count in stale.items():
            if count:
                issues.append(f"graph_stale_{label}:{count}")
        graph_counts = graph.get("counts", {})
        for table, label in [("action_items", "ActionItem"), ("decisions", "Decision"), ("promises", "Promise"), ("transcripts", "Meeting")]:
            if counts.get(table) is not None and graph_counts.get(label) != counts.get(table):
                issues.append(f"graph_count_mismatch:{label}")
    return issues
