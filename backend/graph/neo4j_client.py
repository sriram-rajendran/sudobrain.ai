"""Neo4j knowledge graph client — stores entities and relationships.

All knowledge (people, projects, decisions, promises, topics, meetings)
is stored as nodes with typed edges connecting them.
"""

import logging
import os
import hashlib
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

logger = logging.getLogger("sudobrain.graph")

def _serialize_neo4j(obj):
    """Convert Neo4j types to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _serialize_neo4j(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_neo4j(v) for v in obj]
    if hasattr(obj, 'iso_format'):
        return obj.iso_format()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "sudobrain")

_driver = None


def get_driver():
    """Get or create the Neo4j driver (singleton)."""
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            _driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", NEO4J_URI)
        except Exception as e:
            logger.warning("Neo4j not available: %s", e)
            _driver = None
    return _driver


def is_available() -> bool:
    """Check if Neo4j is running and reachable."""
    driver = get_driver()
    if not driver:
        return False
    try:
        driver.verify_connectivity()
        return True
    except Exception:
        return False


def close():
    """Close the Neo4j driver."""
    global _driver
    if _driver:
        _driver.close()
        _driver = None


def init_schema():
    """Create indexes and constraints for the knowledge graph."""
    driver = get_driver()
    if not driver:
        return

    def run_schema(session, statement: str):
        try:
            session.run(statement)
        except Neo4jError as e:
            code = getattr(e, "code", "") or ""
            message = str(e)
            if "IndexAlreadyExists" in code or "index" in message.lower():
                logger.info("Neo4j schema statement skipped due to existing index: %s", statement)
                return
            raise

    with driver.session() as session:
        # Unique constraints
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (p:Person) ON (p.name)")
        run_schema(session, "CREATE CONSTRAINT IF NOT EXISTS FOR (pr:Project) REQUIRE pr.name IS UNIQUE")
        run_schema(session, "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Decision) REQUIRE d.id IS UNIQUE")
        run_schema(session, "CREATE CONSTRAINT IF NOT EXISTS FOR (a:ActionItem) REQUIRE a.id IS UNIQUE")
        run_schema(session, "CREATE CONSTRAINT IF NOT EXISTS FOR (pm:Promise) REQUIRE pm.id IS UNIQUE")
        run_schema(session, "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Meeting) REQUIRE m.transcript_id IS UNIQUE")

        # Indexes for fast lookup
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (n:Topic) ON (n.name)")
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (n:Decision) ON (n.text)")
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (n:ActionItem) ON (n.text)")
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (n:Promise) ON (n.description)")
        run_schema(session, "CREATE INDEX IF NOT EXISTS FOR (n:Meeting) ON (n.date)")

    logger.info("Neo4j schema initialized")


# --- Node operations ---


def _stable_id(prefix: str, *parts: object) -> str:
    normalized = []
    for part in parts:
        value = "" if part is None else str(part)
        value = re.sub(r"\s+", " ", value.strip()).lower()
        normalized.append(value)
    digest = hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def upsert_person(name: str, email: str = None, role: str = None) -> Optional[dict]:
    """Create or update a Person node."""
    driver = get_driver()
    name = (name or "").strip()
    if not driver or not name:
        return None

    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Person)
            WHERE toLower(p.name) = toLower($name)
               OR ($email IS NOT NULL AND p.email IS NOT NULL AND toLower(p.email) = toLower($email))
            RETURN p, elementId(p) as id
            ORDER BY CASE
                WHEN $email IS NOT NULL AND p.email IS NOT NULL AND toLower(p.email) = toLower($email) THEN 0
                ELSE 1
            END
            LIMIT 1
            """,
            name=name,
            email=email,
        )
        record = result.single()
        if record:
            session.run(
                """
                MATCH (p) WHERE elementId(p) = $id
                SET p.email = COALESCE($email, p.email),
                    p.role = COALESCE($role, p.role),
                    p.updated_at = datetime()
                """,
                id=record["id"],
                email=email,
                role=role,
            )
            return dict(record["p"])

        result = session.run("""
            CREATE (p:Person {name: $name})
            SET p.created_at = datetime(), p.email = $email, p.role = $role
            RETURN p
        """, name=name, email=email, role=role)
        record = result.single()
        return dict(record["p"]) if record else None


def upsert_project(name: str, description: str = None) -> Optional[dict]:
    """Create or update a Project node."""
    driver = get_driver()
    name = (name or "").strip()
    if not driver or not name:
        return None

    with driver.session() as session:
        existing = session.run(
            """
            MATCH (pr:Project)
            WHERE toLower(pr.name) = toLower($name)
            RETURN pr, elementId(pr) AS id
            ORDER BY CASE WHEN pr.repo_path IS NOT NULL THEN 0 ELSE 1 END, pr.name
            LIMIT 1
            """,
            name=name,
        ).single()
        if existing:
            session.run(
                """
                MATCH (pr) WHERE elementId(pr) = $id
                SET pr.description = COALESCE(pr.description, $description),
                    pr.updated_at = datetime()
                RETURN pr
                """,
                id=existing["id"],
                description=description,
            )
            return dict(existing["pr"])

        result = session.run("""
            MERGE (pr:Project {name: $name})
            ON CREATE SET pr.created_at = datetime(), pr.description = $description
            ON MATCH SET pr.description = COALESCE($description, pr.description),
                         pr.updated_at = datetime()
            RETURN pr
        """, name=name, description=description)
        record = result.single()
        return dict(record["pr"]) if record else None


def add_decision(text: str, made_by: str = None, project: str = None,
                 transcript_id: str = None, date: str = None) -> Optional[dict]:
    """Add a Decision node and connect it to people/projects."""
    driver = get_driver()
    text = (text or "").strip()
    if not driver or not text:
        return None

    date = date or datetime.now().isoformat()
    node_id = _stable_id("decision", transcript_id, text, made_by, project)

    from backend.people.name_resolver import resolve_names
    makers = resolve_names([made_by]) if made_by else []

    with driver.session() as session:
        result = session.run("""
            MERGE (d:Decision {id: $id})
            ON CREATE SET d.created_at = datetime()
            SET d.text = $text, d.date = $date, d.transcript_id = $transcript_id,
                d.updated_at = datetime()
            RETURN d, elementId(d) as id
        """, id=node_id, text=text, date=date, transcript_id=transcript_id)
        record = result.single()
        if not record:
            return None
        decision_id = record["id"]

        for name in makers:
            upsert_person(name)
            session.run("""
                MATCH (d) WHERE elementId(d) = $did
                MATCH (p:Person) WHERE toLower(p.name) = toLower($name)
                WITH d, p LIMIT 1
                MERGE (p)-[:MADE_DECISION]->(d)
            """, did=decision_id, name=name)

        if project:
            session.run("""
                MATCH (d) WHERE elementId(d) = $did
                MERGE (pr:Project {name: $project})
                MERGE (d)-[:BELONGS_TO]->(pr)
            """, did=decision_id, project=project)

        return dict(record["d"])


def add_action_item(text: str, assignee: str = None, project: str = None,
                    due_date: str = None, transcript_id: str = None) -> Optional[dict]:
    """Add an ActionItem node and connect to assignee(s)/project.

    Compound assignees like 'Alex and Sam' create links to both people.
    Short names are resolved to canonical full names.
    """
    driver = get_driver()
    text = (text or "").strip()
    if not driver or not text:
        return None

    # Resolve assignee(s) — handles compounds and short->full name resolution
    from backend.people.name_resolver import resolve_names
    assignees = resolve_names([assignee]) if assignee else []
    node_id = _stable_id("action", transcript_id, text, assignee, project, due_date)

    with driver.session() as session:
        result = session.run("""
            MERGE (a:ActionItem {id: $id})
            ON CREATE SET a.created_at = datetime(), a.status = 'pending'
            SET a.text = $text, a.due_date = $due_date,
                a.transcript_id = $transcript_id, a.updated_at = datetime()
            RETURN a, elementId(a) as id
        """, id=node_id, text=text, due_date=due_date, transcript_id=transcript_id)
        record = result.single()
        if not record:
            return None
        item_id = record["id"]

        for name in assignees:
            upsert_person(name)
            session.run("""
                MATCH (a) WHERE elementId(a) = $aid
                MATCH (p:Person) WHERE toLower(p.name) = toLower($name)
                WITH a, p LIMIT 1
                MERGE (a)-[:ASSIGNED_TO]->(p)
            """, aid=item_id, name=name)

        if project:
            session.run("""
                MATCH (a) WHERE elementId(a) = $aid
                MERGE (pr:Project {name: $project})
                MERGE (a)-[:BELONGS_TO]->(pr)
            """, aid=item_id, project=project)

        return dict(record["a"])


def add_promise(description: str, promised_by: str = None, promised_to: str = None,
                due_date: str = None, transcript_id: str = None) -> Optional[dict]:
    """Add a Promise node and connect to people."""
    driver = get_driver()
    description = (description or "").strip()
    if not driver or not description:
        return None

    from backend.people.name_resolver import resolve_names
    from_people = resolve_names([promised_by]) if promised_by else []
    to_people = resolve_names([promised_to]) if promised_to else []
    node_id = _stable_id("promise", transcript_id, description, promised_by, promised_to, due_date)

    with driver.session() as session:
        result = session.run("""
            MERGE (pm:Promise {id: $id})
            ON CREATE SET pm.created_at = datetime(), pm.status = 'pending'
            SET pm.description = $desc, pm.due_date = $due_date,
                pm.transcript_id = $transcript_id, pm.updated_at = datetime()
            RETURN pm, elementId(pm) as id
        """, id=node_id, desc=description, due_date=due_date, transcript_id=transcript_id)
        record = result.single()
        if not record:
            return None
        promise_id = record["id"]

        for name in from_people:
            upsert_person(name)
            session.run("""
                MATCH (pm) WHERE elementId(pm) = $pid
                MATCH (p:Person) WHERE toLower(p.name) = toLower($name)
                WITH pm, p LIMIT 1
                MERGE (p)-[:PROMISED]->(pm)
            """, pid=promise_id, name=name)

        for name in to_people:
            upsert_person(name)
            session.run("""
                MATCH (pm) WHERE elementId(pm) = $pid
                MATCH (p:Person) WHERE toLower(p.name) = toLower($name)
                WITH pm, p LIMIT 1
                MERGE (pm)-[:PROMISED_TO]->(p)
            """, pid=promise_id, name=name)

        return dict(record["pm"])


def add_meeting(transcript_id: str, title: str = None, date: str = None,
                participants: list[str] = None, topics: list[str] = None) -> Optional[dict]:
    """Add a Meeting node and connect to participants and topics."""
    driver = get_driver()
    if not driver:
        return None

    date = date or datetime.now().isoformat()
    title = title or f"Meeting {date[:10]}"

    with driver.session() as session:
        result = session.run("""
            MERGE (m:Meeting {transcript_id: $tid})
            ON CREATE SET m.created_at = datetime()
            SET m.title = $title, m.date = $date, m.updated_at = datetime()
            RETURN m, elementId(m) as id
        """, tid=transcript_id, title=title, date=date)
        record = result.single()
        if not record:
            return None
        meeting_id = record["id"]

        for name in (participants or []):
            upsert_person(name)
            session.run("""
                MATCH (m) WHERE elementId(m) = $mid
                MATCH (p:Person) WHERE toLower(p.name) = toLower($name)
                WITH m, p LIMIT 1
                MERGE (p)-[:ATTENDED]->(m)
            """, mid=meeting_id, name=name)

        for topic in (topics or []):
            session.run("""
                MATCH (m) WHERE elementId(m) = $mid
                MERGE (t:Topic {name: $topic})
                MERGE (m)-[:DISCUSSED]->(t)
            """, mid=meeting_id, topic=topic)

        return dict(record["m"])


def add_topic(name: str, summary: str = None) -> Optional[dict]:
    """Create or update a Topic node."""
    driver = get_driver()
    if not driver:
        return None

    with driver.session() as session:
        result = session.run("""
            MERGE (t:Topic {name: $name})
            ON CREATE SET t.created_at = datetime(), t.summary = $summary
            ON MATCH SET t.summary = COALESCE($summary, t.summary),
                         t.mention_count = COALESCE(t.mention_count, 0) + 1,
                         t.updated_at = datetime()
            RETURN t
        """, name=name, summary=summary)
        record = result.single()
        return dict(record["t"]) if record else None


def link_nodes(from_label: str, from_prop: str, from_value: str,
               to_label: str, to_prop: str, to_value: str,
               relationship: str, properties: dict = None):
    """Create a relationship between two existing nodes."""
    driver = get_driver()
    if not driver:
        return

    props_str = ""
    if properties:
        props_str = " {" + ", ".join(f"{k}: ${k}" for k in properties) + "}"

    query = f"""
        MATCH (a:{from_label} {{{from_prop}: $from_val}})
        MATCH (b:{to_label} {{{to_prop}: $to_val}})
        MERGE (a)-[r:{relationship}{props_str}]->(b)
        RETURN r
    """
    params = {"from_val": from_value, "to_val": to_value}
    if properties:
        params.update(properties)

    with driver.session() as session:
        session.run(query, **params)


# --- Query operations ---


def get_person_network(name: str, depth: int = 2) -> dict:
    """Get a person's full network — connected decisions, promises, projects, meetings."""
    driver = get_driver()
    if not driver:
        return {"person": name, "connections": []}

    with driver.session() as session:
        result = session.run("""
            MATCH (p:Person {name: $name})-[r]-(connected)
            RETURN type(r) as relationship,
                   labels(connected)[0] as node_type,
                   properties(connected) as properties
            ORDER BY connected.created_at DESC
            LIMIT 50
        """, name=name)

        connections = []
        for record in result:
            connections.append({
                "relationship": record["relationship"],
                "node_type": record["node_type"],
                "properties": _serialize_neo4j(dict(record["properties"])),
            })

        return {"person": name, "connections": connections}


def get_project_graph(name: str) -> dict:
    """Get everything connected to a project — people, decisions, tasks, promises."""
    driver = get_driver()
    if not driver:
        return {"project": name, "nodes": []}

    with driver.session() as session:
        result = session.run("""
            MATCH (pr:Project {name: $name})<-[:BELONGS_TO]-(item)
            OPTIONAL MATCH (item)-[r]-(related)
            WHERE NOT related:Project
            RETURN labels(item)[0] as item_type,
                   properties(item) as item_props,
                   type(r) as relationship,
                   labels(related)[0] as related_type,
                   properties(related) as related_props
            LIMIT 100
        """, name=name)

        nodes = []
        for record in result:
            node = {
                "type": record["item_type"],
                "properties": _serialize_neo4j(dict(record["item_props"])),
            }
            if record["related_type"]:
                node["related"] = {
                    "relationship": record["relationship"],
                    "type": record["related_type"],
                    "properties": _serialize_neo4j(dict(record["related_props"])),
                }
            nodes.append(node)

        return {"project": name, "nodes": nodes}


def find_bottlenecks() -> list[dict]:
    """Find people blocking the most action items."""
    driver = get_driver()
    if not driver:
        return []

    with driver.session() as session:
        result = session.run("""
            MATCH (a:ActionItem {status: 'pending'})-[:ASSIGNED_TO]->(p:Person)
            WITH p, COUNT(a) as pending_count, COLLECT(a.text) as tasks
            WHERE pending_count >= 2
            RETURN p.name as person, pending_count, tasks[..5] as top_tasks
            ORDER BY pending_count DESC
            LIMIT 10
        """)
        return [dict(r) for r in result]


def find_orphaned_items() -> dict:
    """Find items not connected to any project."""
    driver = get_driver()
    if not driver:
        return {}

    with driver.session() as session:
        orphan_tasks = session.run("""
            MATCH (a:ActionItem)
            WHERE NOT (a)-[:BELONGS_TO]->(:Project)
            RETURN a.text as text, a.status as status
            LIMIT 20
        """)

        orphan_decisions = session.run("""
            MATCH (d:Decision)
            WHERE NOT (d)-[:BELONGS_TO]->(:Project)
            RETURN d.text as text, d.date as date
            LIMIT 20
        """)

        return {
            "orphaned_tasks": [dict(r) for r in orphan_tasks],
            "orphaned_decisions": [dict(r) for r in orphan_decisions],
        }


def graph_stats() -> dict:
    """Get graph statistics."""
    driver = get_driver()
    if not driver:
        return {"available": False}

    with driver.session() as session:
        counts = {}
        for label in ["Person", "Project", "Decision", "ActionItem", "Promise", "Meeting", "Topic"]:
            result = session.run(f"MATCH (n:{label}) RETURN COUNT(n) as count")
            record = result.single()
            counts[label] = record["count"] if record else 0

        rel_result = session.run("MATCH ()-[r]->() RETURN COUNT(r) as count")
        rel_record = rel_result.single()
        counts["relationships"] = rel_record["count"] if rel_record else 0

        return {"available": True, "counts": counts}


def ingest_knowledge(knowledge: dict, transcript_id: str, meeting_date: str = None,
                     participants: list[str] = None):
    """Ingest extracted knowledge into the graph.

    Takes the output from local_llm_engine.extract_knowledge() and creates
    all nodes and relationships in Neo4j.
    """
    if not is_available():
        return

    project_name = knowledge.get("project")
    if project_name:
        upsert_project(project_name)

    # Topics
    for topic in knowledge.get("topics", []):
        add_topic(topic.get("title", ""), topic.get("summary"))

    # Meeting node
    topic_names = [t.get("title", "") for t in knowledge.get("topics", [])]
    summary = knowledge.get("summary", "")
    if not isinstance(summary, str):
        summary = str(summary)
    add_meeting(
        transcript_id=transcript_id,
        title=summary[:100],
        date=meeting_date,
        participants=participants,
        topics=topic_names,
    )

    # Action items
    for item in knowledge.get("action_items", []):
        add_action_item(
            text=item.get("text", ""),
            assignee=item.get("assignee"),
            project=project_name,
            due_date=item.get("due_date"),
            transcript_id=transcript_id,
        )

    # Decisions
    for item in knowledge.get("decisions", []):
        add_decision(
            text=item.get("text", ""),
            made_by=item.get("made_by"),
            project=project_name,
            transcript_id=transcript_id,
            date=meeting_date,
        )

    # Promises
    for item in knowledge.get("promises", []):
        add_promise(
            description=item.get("text", ""),
            promised_by=item.get("promised_by"),
            promised_to=item.get("promised_to"),
            due_date=item.get("due_date"),
            transcript_id=transcript_id,
        )

    # Participants as Person nodes
    for name in (participants or []):
        upsert_person(name)

    logger.info("Ingested knowledge into graph: transcript=%s, project=%s", transcript_id, project_name)
