"""Task dependency tracking — understand blocking relationships via Neo4j graph."""

import logging
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.task_deps")


def add_dependency(blocker_task_id: int, blocked_task_id: int) -> bool:
    """Mark that blocker_task must complete before blocked_task can start."""
    # Store in SQLite
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_task_id INTEGER NOT NULL,
                blocked_task_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_task_id, blocked_task_id)
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO task_dependencies (blocker_task_id, blocked_task_id) VALUES (?, ?)",
            (blocker_task_id, blocked_task_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Also store in Neo4j if available
    try:
        from backend.graph.neo4j_client import get_driver
        driver = get_driver()
        if driver:
            with driver.session() as session:
                session.run("""
                    MATCH (blocker:ActionItem) WHERE blocker.sqlite_id = $bid
                    MATCH (blocked:ActionItem) WHERE blocked.sqlite_id = $blkd
                    MERGE (blocker)-[:BLOCKS]->(blocked)
                """, bid=blocker_task_id, blkd=blocked_task_id)
    except Exception:
        pass

    return True


def remove_dependency(blocker_task_id: int, blocked_task_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM task_dependencies WHERE blocker_task_id = ? AND blocked_task_id = ?",
            (blocker_task_id, blocked_task_id),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_blocked_tasks() -> list[dict]:
    """Get all tasks that are blocked by other tasks."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_task_id INTEGER NOT NULL,
                blocked_task_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_task_id, blocked_task_id)
            )
        """)
        conn.commit()

        rows = conn.execute("""
            SELECT
                blocked.id as task_id,
                blocked.text as task_text,
                blocked.assignee as task_assignee,
                blocker.id as blocker_id,
                blocker.text as blocker_text,
                blocker.assignee as blocker_assignee,
                blocker.status as blocker_status
            FROM task_dependencies td
            JOIN action_items blocked ON blocked.id = td.blocked_task_id
            JOIN action_items blocker ON blocker.id = td.blocker_task_id
            WHERE blocked.status = 'pending'
            ORDER BY blocked.created_at
        """).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_critical_path() -> list[dict]:
    """Find the longest chain of dependent tasks (critical path)."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_task_id INTEGER NOT NULL,
                blocked_task_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_task_id, blocked_task_id)
            )
        """)

        # Get all dependencies
        deps = conn.execute("SELECT blocker_task_id, blocked_task_id FROM task_dependencies").fetchall()
        tasks = conn.execute("SELECT id, text, assignee, status, due_date FROM action_items WHERE status = 'pending'").fetchall()
    finally:
        conn.close()

    if not deps:
        return []

    # Build adjacency list
    graph = {}
    for d in deps:
        blocker = d["blocker_task_id"]
        blocked = d["blocked_task_id"]
        if blocker not in graph:
            graph[blocker] = []
        graph[blocker].append(blocked)

    task_map = {t["id"]: dict(t) for t in tasks}

    # Find longest path (DFS)
    def dfs(node, visited):
        if node in visited:
            return []
        visited.add(node)
        longest = []
        for child in graph.get(node, []):
            path = dfs(child, visited)
            if len(path) > len(longest):
                longest = path
        visited.discard(node)
        return [node] + longest

    all_roots = set(graph.keys()) - set(d["blocked_task_id"] for d in deps)
    best_path = []
    for root in all_roots:
        path = dfs(root, set())
        if len(path) > len(best_path):
            best_path = path

    return [task_map.get(tid, {"id": tid, "text": "unknown"}) for tid in best_path]


def get_blocking_summary() -> dict:
    """Get a summary of what's blocking what, grouped by blocker person."""
    blocked = get_blocked_tasks()
    if not blocked:
        return {"blockers": [], "total_blocked": 0}

    by_person = {}
    for item in blocked:
        person = item.get("blocker_assignee") or "Unassigned"
        if person not in by_person:
            by_person[person] = {"person": person, "blocking_count": 0, "blocked_tasks": []}
        by_person[person]["blocking_count"] += 1
        by_person[person]["blocked_tasks"].append(item["task_text"])

    blockers = sorted(by_person.values(), key=lambda x: x["blocking_count"], reverse=True)
    return {"blockers": blockers, "total_blocked": len(blocked)}
