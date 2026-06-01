"""Knowledge quality normalization and audit.

Keeps extracted knowledge aligned with configured project context and canonical
people identities. This is deliberately conservative: it normalizes clear
aliases and leaves genuinely unknown external names untouched.
"""

from __future__ import annotations

import re
import json
import os
from dataclasses import dataclass

from backend.storage.database import get_connection


def _json_dict_env(name: str) -> dict:
    try:
        value = os.getenv(name, "{}") or "{}"
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _csv_set_env(name: str) -> set[str]:
    return {item.strip() for item in (os.getenv(name, "") or "").split(",") if item.strip()}


def _pattern_map_from_env() -> list[tuple[str, list[str]]]:
    raw = _json_dict_env("SUDOBRAIN_PROJECT_PATTERNS_JSON")
    out: list[tuple[str, list[str]]] = []
    for canonical, patterns in raw.items():
        if isinstance(canonical, str) and isinstance(patterns, list):
            out.append((canonical, [p for p in patterns if isinstance(p, str)]))
    return out


JUNK_PERSON_TERMS = {
    "",
    "both",
    "channel",
    "client",
    "engineering channel",
    "everyone",
    "internship mentor (recipient)",
    "organization mentor",
    "product",
    "product team",
    "speaker",
    "speaker 0",
    "team",
    "team consensus",
    "teammate",
    "the team",
    "unassigned",
    "unknown",
    "unspecified",
    "who",
}

PERSON_ALIASES = _json_dict_env("SUDOBRAIN_PERSON_ALIASES_JSON")
SLACK_ID_OVERRIDES = _json_dict_env("SUDOBRAIN_SLACK_ID_OVERRIDES_JSON")
EMAIL_NAME_OVERRIDES = {k.lower(): v for k, v in _json_dict_env("SUDOBRAIN_EMAIL_NAME_OVERRIDES_JSON").items()}
ACCEPTED_NON_REPO_PROJECTS = _csv_set_env("SUDOBRAIN_ACCEPTED_EXTERNAL_PROJECTS")
PROJECT_PATTERN_MAP = _pattern_map_from_env()
STRICT_PROJECT_AUDIT = (os.getenv("SUDOBRAIN_STRICT_PROJECT_AUDIT", "false") or "").lower() == "true"


@dataclass
class KnowledgeQualityResult:
    project_updates: int
    people_field_updates: int
    people_table_updates: int
    graph_rebuilt: dict


def normalize_project_name(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for canonical, patterns in PROJECT_PATTERN_MAP:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return canonical
    return text


def normalize_person_field(value: str | None) -> str | None:
    if not value:
        return None
    email_map, slack_map = _identity_maps()
    parts = _split_people(value)
    resolved = []
    seen = set()
    for part in parts:
        name = _normalize_single_person(part, email_map, slack_map)
        if not name:
            continue
        key = _norm(name)
        if key not in seen:
            seen.add(key)
            resolved.append(name)
    if not resolved:
        return None
    return ", ".join(resolved)


def apply_quality_fixes(rebuild_graph: bool = True) -> dict:
    project_updates = _normalize_knowledge_projects()
    people_table_updates = _normalize_people_table()
    people_field_updates = _normalize_knowledge_people()
    graph_rebuilt = rebuild_knowledge_graph() if rebuild_graph else {}
    return KnowledgeQualityResult(
        project_updates=project_updates,
        people_field_updates=people_field_updates,
        people_table_updates=people_table_updates,
        graph_rebuilt=graph_rebuilt,
    ).__dict__


def collect_knowledge_quality_audit() -> dict:
    conn = get_connection()
    try:
        project_values = _project_value_rows(conn)
        person_values = _person_value_rows(conn)
        unresolved_projects = [
            row for row in project_values
            if STRICT_PROJECT_AUDIT
            and row["project"]
            and normalize_project_name(row["project"]) == row["project"]
            and not _project_exists(conn, row["project"])
            and row["project"] not in ACCEPTED_NON_REPO_PROJECTS
        ]
        unresolved_people = [
            row for row in person_values
            if row["name"] and _person_quality_issue(row["name"])
        ]
    finally:
        conn.close()
    graph = _graph_person_quality()
    issues = []
    if unresolved_projects:
        issues.append("unresolved_project_values")
    if unresolved_people:
        issues.append("weak_person_values")
    if graph.get("junk_person_nodes"):
        issues.append("graph_junk_person_nodes")
    if graph.get("duplicate_person_emails"):
        issues.append("graph_duplicate_person_emails")
    return {
        "status": "ok" if not issues else "warning",
        "issues": issues,
        "unresolved_projects": unresolved_projects[:50],
        "weak_person_values": unresolved_people[:80],
        "graph": graph,
    }


def rebuild_knowledge_graph() -> dict:
    """Rebuild derived knowledge nodes from Postgres canonical fields."""
    from backend.graph.neo4j_client import add_action_item, add_decision, add_meeting, add_promise, get_driver

    driver = get_driver()
    if not driver:
        return {"skipped": "neo4j_unavailable"}

    with driver.session() as session:
        _normalize_graph_people_names(session)
        for label in ["ActionItem", "Decision", "Promise", "Meeting"]:
            session.run(f"MATCH (n:{label}) DETACH DELETE n")
        _merge_graph_people(session)

    conn = get_connection()
    try:
        transcripts = conn.execute("SELECT id, processed_at, transcript_json FROM transcripts").fetchall()
        actions = conn.execute("SELECT transcript_id, text, assignee, project, due_date FROM action_items").fetchall()
        decisions = conn.execute("SELECT transcript_id, text, made_by, project, created_at FROM decisions").fetchall()
        promises = conn.execute("SELECT transcript_id, description, promised_by_name, promised_to_name, due_date FROM promises").fetchall()
    finally:
        conn.close()

    meetings = 0
    for row in transcripts:
        title, date, participants = _meeting_from_transcript(row)
        add_meeting(row["id"], title=title, date=date, participants=participants)
        meetings += 1
    for row in actions:
        add_action_item(
            row["text"],
            assignee=row["assignee"],
            project=row["project"],
            due_date=str(row["due_date"]) if row["due_date"] else None,
            transcript_id=row["transcript_id"],
        )
    for row in decisions:
        add_decision(
            row["text"],
            made_by=row["made_by"],
            project=row["project"],
            transcript_id=row["transcript_id"],
            date=str(row["created_at"]) if row["created_at"] else None,
        )
    for row in promises:
        add_promise(
            row["description"],
            promised_by=row["promised_by_name"],
            promised_to=row["promised_to_name"],
            due_date=str(row["due_date"]) if row["due_date"] else None,
            transcript_id=row["transcript_id"],
        )

    with driver.session() as session:
        _normalize_graph_people_names(session)
        junk_deleted = _delete_graph_junk_people(session)
        _merge_graph_people(session)

    return {
        "meetings": meetings,
        "actions": len(actions),
        "decisions": len(decisions),
        "promises": len(promises),
        "junk_people_deleted": junk_deleted,
    }


def _identity_maps() -> tuple[dict[str, str], dict[str, str]]:
    conn = get_connection()
    email_map = dict(EMAIL_NAME_OVERRIDES)
    slack_map = {}
    try:
        for row in conn.execute("SELECT id, real_name, name, email FROM slack_users").fetchall():
            display = EMAIL_NAME_OVERRIDES.get((row["email"] or "").lower()) or row["real_name"] or row["name"]
            if row["id"] and display:
                slack_map[row["id"]] = display
            if row["email"] and display:
                email_map[row["email"].lower()] = display
        for row in conn.execute("SELECT name, email FROM people WHERE email IS NOT NULL AND email <> ''").fetchall():
            email = row["email"].lower()
            email_map.setdefault(email, EMAIL_NAME_OVERRIDES.get(email) or row["name"])
    finally:
        conn.close()
    slack_map.update(SLACK_ID_OVERRIDES)
    return email_map, slack_map


def _normalize_single_person(value: str, email_map: dict[str, str], slack_map: dict[str, str]) -> str | None:
    text = _clean_person_text(value)
    if not text:
        return None

    for uid in re.findall(r"U[A-Z0-9]{8,}", text):
        if uid in slack_map:
            return slack_map[uid]
        if uid in SLACK_ID_OVERRIDES:
            return SLACK_ID_OVERRIDES[uid]

    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if email_match:
        email = email_match.group(0).lower()
        return email_map.get(email) or email

    key = _norm_phrase(text)
    if _is_junk_person(text):
        return None
    if key in PERSON_ALIASES:
        return PERSON_ALIASES[key]
    return text.strip()


def _split_people(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    # Preserve parenthetical aliases before separator handling.
    text = re.sub(r"\s+\+\s+", ",", text)
    text = re.sub(r"\s+&\s+", ",", text)
    text = re.sub(r"\s+and\s+", ",", text, flags=re.I)
    text = re.sub(r"\s*/\s*", ",", text)
    return [p.strip() for p in text.split(",") if p.strip()]


def _clean_person_text(value: str) -> str:
    text = (value or "").strip()
    text = text.replace("<@", "").replace(">", "")
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" -:;")
    return text


def _is_junk_person(value: str) -> bool:
    key = _norm_phrase(value)
    if key in JUNK_PERSON_TERMS:
        return True
    if "team" in key and key not in PERSON_ALIASES:
        return True
    if key.endswith(" channel"):
        return True
    return False


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _norm_phrase(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9@.+-]+", " ", (value or "").lower())).strip()


def _normalize_knowledge_projects() -> int:
    conn = get_connection()
    updates = 0
    try:
        for table in ["action_items", "decisions"]:
            rows = conn.execute(f"SELECT id, project FROM {table}").fetchall()
            for row in rows:
                canonical = normalize_project_name(row["project"])
                current = (row["project"] or None)
                if canonical != current:
                    conn.execute(f"UPDATE {table} SET project = ? WHERE id = ?", (canonical, row["id"]))
                    updates += 1
        conn.commit()
    finally:
        conn.close()
    return updates


def _normalize_knowledge_people() -> int:
    conn = get_connection()
    updates = 0
    try:
        for table, column in [
            ("action_items", "assignee"),
            ("decisions", "made_by"),
            ("promises", "promised_by_name"),
            ("promises", "promised_to_name"),
        ]:
            rows = conn.execute(f"SELECT id, {column} value FROM {table}").fetchall()
            for row in rows:
                canonical = normalize_person_field(row["value"])
                current = row["value"] or None
                if canonical != current:
                    conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (canonical, row["id"]))
                    updates += 1
        conn.commit()
    finally:
        conn.close()
    return updates


def _normalize_people_table() -> int:
    conn = get_connection()
    updates = 0
    try:
        for email, name in EMAIL_NAME_OVERRIDES.items():
            cur = conn.execute(
                "UPDATE people SET name = ? WHERE LOWER(email) = ? AND name <> ?",
                (name, email, name),
            )
            updates += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        conn.close()
    return updates


def _project_value_rows(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT project, SUM(c) c FROM (
            SELECT project, COUNT(*) c FROM action_items WHERE project IS NOT NULL AND TRIM(project) <> '' GROUP BY project
            UNION ALL
            SELECT project, COUNT(*) c FROM decisions WHERE project IS NOT NULL AND TRIM(project) <> '' GROUP BY project
        ) x
        GROUP BY project
        ORDER BY c DESC, project
    """).fetchall()
    return [dict(row) for row in rows]


def _project_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM projects WHERE name = ? LIMIT 1", (name,)).fetchone()
    return bool(row)


def _person_value_rows(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT name, SUM(c) c FROM (
            SELECT assignee name, COUNT(*) c FROM action_items WHERE assignee IS NOT NULL AND TRIM(assignee) <> '' GROUP BY assignee
            UNION ALL
            SELECT made_by name, COUNT(*) c FROM decisions WHERE made_by IS NOT NULL AND TRIM(made_by) <> '' GROUP BY made_by
            UNION ALL
            SELECT promised_by_name name, COUNT(*) c FROM promises WHERE promised_by_name IS NOT NULL AND TRIM(promised_by_name) <> '' GROUP BY promised_by_name
            UNION ALL
            SELECT promised_to_name name, COUNT(*) c FROM promises WHERE promised_to_name IS NOT NULL AND TRIM(promised_to_name) <> '' GROUP BY promised_to_name
        ) x
        GROUP BY name
        ORDER BY c DESC, name
    """).fetchall()
    return [dict(row) for row in rows]


def _person_quality_issue(value: str) -> bool:
    if _is_junk_person(value):
        return True
    if re.search(r"<@|U[A-Z0-9]{8,}", value):
        return True
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value):
        return True
    return False


def _graph_person_quality() -> dict:
    try:
        from backend.graph.neo4j_client import get_driver

        driver = get_driver()
        if not driver:
            return {"available": False}
        with driver.session() as session:
            people = session.run(
                "MATCH (p:Person) RETURN p.name AS name, p.email AS email, COUNT { (p)--() } AS degree"
            ).data()
            junk = [p for p in people if _person_quality_issue(p.get("name") or "")]
            duplicate_emails = session.run("""
                MATCH (p:Person)
                WHERE p.email IS NOT NULL AND p.email <> ''
                WITH toLower(p.email) AS email, COUNT(*) AS c
                WHERE c > 1
                RETURN email, c
            """).data()
        return {
            "available": True,
            "junk_person_nodes": sorted(junk, key=lambda p: (-p["degree"], p.get("name") or ""))[:80],
            "duplicate_person_emails": duplicate_emails,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def _meeting_from_transcript(row) -> tuple[str, str | None, list[str]]:
    try:
        blob = json.loads(row["transcript_json"] or "{}")
    except Exception:
        blob = {}
    participants = []
    for participant in blob.get("participants") or []:
        if isinstance(participant, dict):
            name = participant.get("label") or participant.get("name") or participant.get("speaker_id") or ""
        else:
            name = str(participant)
        normalized = normalize_person_field(name)
        if normalized:
            participants.extend(_split_people(normalized))
    source = blob.get("source") or "transcript"
    title = (blob.get("title") or f"{source} {row['id']}")[:100]
    date = blob.get("created_at") or row["processed_at"]
    return title, str(date) if date else None, participants


def _merge_graph_people(session):
    _merge_graph_person_groups(session, """
        MATCH (p:Person)
        WITH coalesce(toLower(p.email), toLower(p.name)) AS key,
             collect({eid: elementId(p), name: p.name, email: p.email, degree: COUNT { (p)--() }}) AS nodes,
             COUNT(*) AS c
        WHERE key IS NOT NULL AND key <> '' AND c > 1
        RETURN key, nodes
    """)
    _merge_graph_person_groups(session, """
        MATCH (p:Person)
        WHERE p.name IS NOT NULL AND trim(p.name) <> ''
        WITH toLower(p.name) AS key,
             collect({eid: elementId(p), name: p.name, email: p.email, degree: COUNT { (p)--() }}) AS nodes,
             COUNT(*) AS c
        WHERE key IS NOT NULL AND key <> '' AND c > 1
        RETURN key, nodes
    """)


def _merge_graph_person_groups(session, query: str):
    groups = session.run(query).data()
    for group in groups:
        nodes = sorted(group["nodes"], key=lambda n: (0 if n.get("email") else 1, -n.get("degree", 0), n.get("name") or ""))
        target = nodes[0]
        for duplicate in nodes[1:]:
            _transfer_graph_relationships(session, duplicate["eid"], target["eid"])
            session.run(
                """
                MATCH (target) WHERE elementId(target) = $target
                MATCH (dup) WHERE elementId(dup) = $dup
                SET target.email = COALESCE(target.email, dup.email),
                    target.alternate_emails = CASE
                        WHEN dup.email IS NOT NULL
                         AND target.email IS NOT NULL
                         AND toLower(dup.email) <> toLower(target.email)
                        THEN coalesce(target.alternate_emails, []) + dup.email
                        ELSE coalesce(target.alternate_emails, [])
                    END,
                    target.updated_at = datetime()
                DETACH DELETE dup
                """,
                target=target["eid"],
                dup=duplicate["eid"],
            )


def _normalize_graph_people_names(session):
    for email, name in EMAIL_NAME_OVERRIDES.items():
        session.run(
            """
            MATCH (p:Person)
            WHERE p.email IS NOT NULL AND toLower(p.email) = $email
            SET p.name = $name, p.updated_at = datetime()
            """,
            email=email,
            name=name,
        )


def _delete_graph_junk_people(session) -> int:
    people = session.run("MATCH (p:Person) RETURN elementId(p) AS eid, p.name AS name").data()
    deleted = 0
    for person in people:
        if _person_quality_issue(person.get("name") or ""):
            session.run("MATCH (p) WHERE elementId(p) = $eid DETACH DELETE p", eid=person["eid"])
            deleted += 1
    return deleted


def _transfer_graph_relationships(session, source_eid: str, target_eid: str):
    for row in session.run(
        """
        MATCH (src)-[r]->(other)
        WHERE elementId(src) = $source AND elementId(other) <> $target
        RETURN type(r) AS rel_type, properties(r) AS props, elementId(other) AS other
        """,
        source=source_eid,
        target=target_eid,
    ).data():
        _merge_relationship(session, target_eid, row["other"], row["rel_type"], row["props"], outgoing=True)
    for row in session.run(
        """
        MATCH (other)-[r]->(src)
        WHERE elementId(src) = $source AND elementId(other) <> $target
        RETURN type(r) AS rel_type, properties(r) AS props, elementId(other) AS other
        """,
        source=source_eid,
        target=target_eid,
    ).data():
        _merge_relationship(session, target_eid, row["other"], row["rel_type"], row["props"], outgoing=False)


def _merge_relationship(session, target_eid: str, other_eid: str, rel_type: str, props: dict, outgoing: bool):
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", rel_type or ""):
        return
    if outgoing:
        query = f"""
            MATCH (target) WHERE elementId(target) = $target
            MATCH (other) WHERE elementId(other) = $other
            MERGE (target)-[r:{rel_type}]->(other)
            SET r += $props
        """
    else:
        query = f"""
            MATCH (target) WHERE elementId(target) = $target
            MATCH (other) WHERE elementId(other) = $other
            MERGE (other)-[r:{rel_type}]->(target)
            SET r += $props
        """
    session.run(query, target=target_eid, other=other_eid, props=props or {})
