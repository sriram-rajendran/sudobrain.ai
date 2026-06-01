"""Rebuild Neo4j graph from canonical data.

Strategy:
1. Wipe existing graph
2. Seed Person nodes ONLY from the canonical `people` table (keyed on email)
3. Seed Project, LinearIssue, SlackChannel, Meeting nodes from raw tables
4. Create structural edges from raw data (no LLM):
   - (Person)-[:SENT]->(SlackChannel)  (authored messages in)
   - (Person)-[:AUTHORED]->(LinearIssue)
   - (Person)-[:ASSIGNED]->(LinearIssue)
   - (Person)-[:EMAILED]->(Person)
   - (LinearIssue)-[:IN_PROJECT]->(Project)
5. Layer extracted edges from Postgres knowledge tables using name resolution to
   canonical person_ids.
"""

import logging
import sys
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("rebuild_graph")

from backend.storage.database import get_connection
from backend.graph.neo4j_client import get_driver


def wipe():
    d = get_driver()
    with d.session() as s:
        before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        s.run("MATCH (n) DETACH DELETE n")
        logger.info("wiped %d nodes", before)


def seed_schema():
    d = get_driver()
    with d.session() as s:
        for cypher in [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:LinearIssue) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:SlackChannel) REQUIRE c.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (p:Person) ON (p.name)",
        ]:
            try:
                s.run(cypher)
            except Exception as e:
                logger.debug("schema stmt skipped: %s", e)


def seed_people():
    """Load all canonical people into Neo4j."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, email, organization, is_self FROM people"
    ).fetchall()
    conn.close()

    d = get_driver()
    with d.session() as s:
        for r in rows:
            s.run(
                """
                MERGE (p:Person {email: $email})
                SET p.id = $id, p.name = $name, p.organization = $org, p.is_self = $is_self
                """,
                email=r["email"],
                id=r["id"],
                name=r["name"],
                org=r["organization"] or "",
                is_self=bool(r["is_self"]),
            )
    logger.info("seeded %d Person nodes", len(rows))


def seed_linear():
    """Load LinearIssue + Project nodes, link assignees/creators to Person."""
    conn = get_connection()
    try:
        projects = conn.execute("SELECT id, name, description, state FROM linear_projects").fetchall()
        issues = conn.execute(
            """
            SELECT id, title, state_name, state_type, priority_label,
                   assignee_email, creator_name, project_name, team_name,
                   due_date, url, updated_at, created_at
            FROM linear_issues
            """
        ).fetchall()
    finally:
        conn.close()

    d = get_driver()
    with d.session() as s:
        for p in projects:
            s.run(
                "MERGE (pr:Project {name: $name}) SET pr.id=$id, pr.description=$desc, pr.state=$state",
                name=p["name"],
                id=p["id"],
                desc=p["description"] or "",
                state=p["state"] or "",
            )
        for i in issues:
            s.run(
                """
                MERGE (li:LinearIssue {id: $id})
                SET li.title=$title, li.state=$state, li.state_type=$stype,
                    li.priority=$prio, li.due_date=$due, li.url=$url,
                    li.updated_at=$updated, li.created_at=$created
                """,
                id=i["id"],
                title=i["title"] or "",
                state=i["state_name"] or "",
                stype=i["state_type"] or "",
                prio=i["priority_label"] or "",
                due=str(i["due_date"]) if i["due_date"] else None,
                url=i["url"] or "",
                updated=str(i["updated_at"]) if i["updated_at"] else None,
                created=str(i["created_at"]) if i["created_at"] else None,
            )
            # Link to project
            if i["project_name"]:
                s.run(
                    "MATCH (li:LinearIssue {id: $iid}), (pr:Project {name: $pname}) "
                    "MERGE (li)-[:IN_PROJECT]->(pr)",
                    iid=i["id"],
                    pname=i["project_name"],
                )
            # Link to assignee (by canonical email)
            if i["assignee_email"]:
                s.run(
                    "MATCH (li:LinearIssue {id: $iid}), (p:Person {email: $em}) "
                    "MERGE (p)-[:ASSIGNED_TO]->(li)",
                    iid=i["id"],
                    em=i["assignee_email"].lower(),
                )
    logger.info("seeded %d projects, %d issues", len(projects), len(issues))


def seed_slack():
    """Seed SlackChannel nodes + SENT edges from messages."""
    conn = get_connection()
    try:
        channels = conn.execute(
            "SELECT id, name, is_private FROM slack_channels WHERE sync_enabled=TRUE"
        ).fetchall()
        # Join messages with slack_users to get person_id / email
        msg_links = conn.execute(
            """
            SELECT m.channel_id, p.email, COUNT(*) c
            FROM slack_messages m
            JOIN slack_users su ON su.id = m.user_id
            JOIN people p ON p.id = su.person_id
            WHERE p.email IS NOT NULL
            GROUP BY m.channel_id, p.email
            """
        ).fetchall()
    finally:
        conn.close()

    d = get_driver()
    with d.session() as s:
        for c in channels:
            s.run(
                "MERGE (ch:SlackChannel {id: $id}) SET ch.name=$name, ch.is_private=$pri",
                id=c["id"],
                name=c["name"] or "",
                pri=bool(c["is_private"]),
            )
        for m in msg_links:
            s.run(
                """
                MATCH (p:Person {email: $em}), (ch:SlackChannel {id: $cid})
                MERGE (p)-[r:SENT]->(ch)
                SET r.count = $cnt
                """,
                em=m["email"].lower(),
                cid=m["channel_id"],
                cnt=m["c"],
            )
    logger.info("seeded %d channels, %d SENT edges", len(channels), len(msg_links))


def seed_email_edges():
    """Create EMAILED edges from gmail_messages (from_email -> to_emails)."""
    import json
    from email.utils import getaddresses

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT from_email, to_emails FROM gmail_messages "
            "WHERE from_email IS NOT NULL AND to_emails IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    edges = {}  # (from, to) -> count
    for r in rows:
        sender = (r["from_email"] or "").lower()
        if not sender:
            continue
        try:
            chunks = json.loads(r["to_emails"] or "[]")
            for _, e in getaddresses(chunks):
                if "@" in e:
                    key = (sender, e.lower())
                    edges[key] = edges.get(key, 0) + 1
        except Exception:
            pass

    d = get_driver()
    with d.session() as s:
        for (sender, receiver), cnt in edges.items():
            s.run(
                """
                MATCH (a:Person {email: $a}), (b:Person {email: $b})
                MERGE (a)-[r:EMAILED]->(b)
                SET r.count = $cnt
                """,
                a=sender,
                b=receiver,
                cnt=cnt,
            )
    logger.info("seeded %d EMAILED edges (unique sender→recipient pairs)", len(edges))


def layer_extracted_edges():
    """Link extracted action_items/decisions/promises to canonical people via fuzzy resolve."""
    from backend.people.canonical import resolve_by_name, resolve_by_email

    conn = get_connection()
    try:
        # Promises: promised_by_name / promised_to_name
        promises = conn.execute(
            "SELECT id, description, promised_by_name, promised_to_name, due_date FROM promises"
        ).fetchall()
        # Action items: assignee
        actions = conn.execute(
            "SELECT id, text, assignee, project, due_date FROM action_items"
        ).fetchall()
        # Decisions: made_by
        decisions = conn.execute(
            "SELECT id, text, made_by, project FROM decisions"
        ).fetchall()
    finally:
        conn.close()

    d = get_driver()
    linked = {"promise": 0, "action": 0, "decision": 0}

    with d.session() as s:
        # Promises
        for p in promises:
            by_id = resolve_by_name(p["promised_by_name"] or "")
            to_id = resolve_by_name(p["promised_to_name"] or "")
            s.run(
                "MERGE (pr:Promise {id: $id}) SET pr.description=$desc, pr.due_date=$due",
                id=p["id"],
                desc=p["description"] or "",
                due=str(p["due_date"]) if p["due_date"] else None,
            )
            if by_id:
                s.run(
                    "MATCH (a:Person {id: $pid}), (pr:Promise {id: $prid}) MERGE (a)-[:PROMISED]->(pr)",
                    pid=by_id, prid=p["id"],
                )
                linked["promise"] += 1
            if to_id:
                s.run(
                    "MATCH (b:Person {id: $pid}), (pr:Promise {id: $prid}) MERGE (pr)-[:PROMISED_TO]->(b)",
                    pid=to_id, prid=p["id"],
                )

        # Action items
        for a in actions:
            aid = resolve_by_name(a["assignee"] or "")
            s.run(
                "MERGE (ai:ActionItem {id: $id}) SET ai.text=$t, ai.project=$proj, ai.due_date=$due",
                id=a["id"],
                t=a["text"] or "",
                proj=a["project"] or "",
                due=str(a["due_date"]) if a["due_date"] else None,
            )
            if aid:
                s.run(
                    "MATCH (p:Person {id: $pid}), (ai:ActionItem {id: $aid}) MERGE (ai)-[:ASSIGNED_TO]->(p)",
                    pid=aid, aid=a["id"],
                )
                linked["action"] += 1
            if a["project"]:
                s.run(
                    "MATCH (ai:ActionItem {id: $aid}) MERGE (pr:Project {name: $pn}) MERGE (ai)-[:IN_PROJECT]->(pr)",
                    aid=a["id"], pn=a["project"],
                )

        # Decisions
        for de in decisions:
            mid = resolve_by_name(de["made_by"] or "")
            s.run(
                "MERGE (d:Decision {id: $id}) SET d.text=$t, d.project=$proj",
                id=de["id"], t=de["text"] or "", proj=de["project"] or "",
            )
            if mid:
                s.run(
                    "MATCH (p:Person {id: $pid}), (d:Decision {id: $did}) MERGE (p)-[:MADE]->(d)",
                    pid=mid, did=de["id"],
                )
                linked["decision"] += 1
            if de["project"]:
                s.run(
                    "MATCH (d:Decision {id: $did}) MERGE (pr:Project {name: $pn}) MERGE (d)-[:IN_PROJECT]->(pr)",
                    did=de["id"], pn=de["project"],
                )

    logger.info("layered extracted edges: %s", linked)


def stats():
    d = get_driver()
    with d.session() as s:
        counts = {}
        for label in ["Person", "Project", "LinearIssue", "SlackChannel", "Promise", "ActionItem", "Decision", "Topic"]:
            r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
            counts[label] = r["c"] if r else 0
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        counts["relationships"] = r["c"]
        return counts


def main():
    logger.info("step 1: wipe")
    wipe()
    logger.info("step 2: schema")
    seed_schema()
    logger.info("step 3: seed people")
    seed_people()
    logger.info("step 4: seed linear")
    seed_linear()
    logger.info("step 5: seed slack")
    seed_slack()
    logger.info("step 6: seed email edges")
    seed_email_edges()
    logger.info("step 7: layer extracted edges")
    layer_extracted_edges()
    logger.info("done. stats: %s", stats())


if __name__ == "__main__":
    main()
