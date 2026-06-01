"""Automated workflows / triggers — rule engine for SudoBrain.

Define rules: when X happens, do Y. Rules are stored in the database
and evaluated by the heartbeat engine.
"""

import logging
from datetime import datetime, date, timedelta
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.workflows")


def init_workflow_tables():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                condition_json TEXT,
                action_type TEXT NOT NULL,
                action_params_json TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                last_triggered DATETIME,
                trigger_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS workflow_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER REFERENCES workflow_rules(id),
                rule_name TEXT,
                trigger_type TEXT,
                action_type TEXT,
                result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    finally:
        conn.close()


def create_rule(name: str, trigger_type: str, action_type: str,
                condition: dict = None, action_params: dict = None) -> int:
    """Create a new workflow rule.

    Trigger types: promise_due_soon, task_overdue, no_interaction, recording_processed
    Action types: notify, create_reminder, send_email_draft, flag_inbox
    """
    import json
    init_workflow_tables()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO workflow_rules (name, trigger_type, condition_json, action_type, action_params_json)
            VALUES (?, ?, ?, ?, ?)""",
            (name, trigger_type, json.dumps(condition or {}), action_type, json.dumps(action_params or {})),
        )
        conn.commit()
        rule_id = cursor.lastrowid
        logger.info("Workflow rule created: #%d %s", rule_id, name)
        return rule_id
    finally:
        conn.close()


def list_rules() -> list[dict]:
    init_workflow_tables()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM workflow_rules ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def toggle_rule(rule_id: int, enabled: bool) -> bool:
    conn = get_connection()
    try:
        conn.execute("UPDATE workflow_rules SET enabled = ? WHERE id = ?", (enabled, rule_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_rule(rule_id: int, name: str | None = None, trigger_type: str | None = None,
                action_type: str | None = None, condition: dict | None = None,
                action_params: dict | None = None, enabled: bool | None = None) -> bool:
    """Update editable workflow fields."""
    import json
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if trigger_type is not None:
        updates.append("trigger_type = ?")
        params.append(trigger_type)
    if action_type is not None:
        updates.append("action_type = ?")
        params.append(action_type)
    if condition is not None:
        updates.append("condition_json = ?")
        params.append(json.dumps(condition))
    if action_params is not None:
        updates.append("action_params_json = ?")
        params.append(json.dumps(action_params))
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(enabled)
    if not updates:
        return False

    params.append(rule_id)
    conn = get_connection()
    try:
        result = conn.execute(f"UPDATE workflow_rules SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def delete_rule(rule_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM workflow_rules WHERE id = ?", (rule_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def _log_trigger(rule_id: int, rule_name: str, trigger_type: str, action_type: str, result: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO workflow_log (rule_id, rule_name, trigger_type, action_type, result) VALUES (?, ?, ?, ?, ?)",
            (rule_id, rule_name, trigger_type, action_type, result),
        )
        conn.execute(
            "UPDATE workflow_rules SET last_triggered = ?, trigger_count = trigger_count + 1 WHERE id = ?",
            (datetime.now().isoformat(), rule_id),
        )
        conn.commit()
    finally:
        conn.close()


def evaluate_rules():
    """Evaluate all enabled rules. Called by heartbeat engine.

    Returns list of triggered actions.
    """
    import json
    init_workflow_tables()
    conn = get_connection()
    try:
        rules = conn.execute(
            "SELECT * FROM workflow_rules WHERE enabled = TRUE"
        ).fetchall()
    finally:
        conn.close()

    triggered = []

    for rule in rules:
        rule = dict(rule)
        trigger_type = rule["trigger_type"]
        condition = json.loads(rule.get("condition_json") or "{}")
        action_type = rule["action_type"]
        action_params = json.loads(rule.get("action_params_json") or "{}")

        items = _check_trigger(trigger_type, condition)
        if not items:
            continue

        for item in items:
            result = _execute_action(action_type, action_params, item)
            _log_trigger(rule["id"], rule["name"], trigger_type, action_type, result)
            triggered.append({
                "rule": rule["name"],
                "trigger": trigger_type,
                "action": action_type,
                "item": item,
                "result": result,
            })

    if triggered:
        logger.info("Workflows: %d rules triggered", len(triggered))
    return triggered


def preview_rule(rule_id: int | None = None, trigger_type: str | None = None,
                 condition: dict | None = None, limit: int = 20) -> dict:
    """Return matching trigger items without executing actions."""
    import json
    if rule_id is not None:
        init_workflow_tables()
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM workflow_rules WHERE id = ?", (rule_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return {"matches": [], "count": 0}
        trigger_type = row["trigger_type"]
        condition = json.loads(row.get("condition_json") or "{}")
    if not trigger_type:
        return {"matches": [], "count": 0}
    matches = _check_trigger(trigger_type, condition or {})
    return {"trigger_type": trigger_type, "matches": matches[:limit], "count": len(matches)}


def _check_trigger(trigger_type: str, condition: dict) -> list[dict]:
    """Check if a trigger condition is met. Returns matching items."""
    conn = get_connection()
    try:
        if trigger_type == "promise_due_soon":
            days = condition.get("days_before", 2)
            threshold = (date.today() + timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT id, description, promised_by_name, promised_to_name, due_date
                FROM promises WHERE status = 'pending' AND due_date IS NOT NULL
                AND due_date <= ? AND due_date >= date('now')""",
                (threshold,),
            ).fetchall()
            return [dict(r) for r in rows]

        elif trigger_type == "task_overdue":
            rows = conn.execute(
                """SELECT id, text, assignee, due_date FROM action_items
                WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < date('now')"""
            ).fetchall()
            return [dict(r) for r in rows]

        elif trigger_type == "no_interaction":
            days = condition.get("days_threshold", 30)
            threshold = (date.today() - timedelta(days=days)).isoformat()
            try:
                rows = conn.execute(
                    """SELECT id, name, last_interaction FROM people
                    WHERE is_self = FALSE AND last_interaction IS NOT NULL
                    AND last_interaction < ?""",
                    (threshold,),
                ).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

        elif trigger_type == "unassigned_task":
            hours = condition.get("hours_threshold", 24)
            threshold = (datetime.now() - timedelta(hours=hours)).isoformat()
            rows = conn.execute(
                """SELECT id, text, created_at FROM action_items
                WHERE status = 'pending' AND (assignee IS NULL OR assignee = '')
                AND created_at < ?""",
                (threshold,),
            ).fetchall()
            return [dict(r) for r in rows]

    except Exception as e:
        logger.warning("Trigger check failed for %s: %s", trigger_type, e)
    finally:
        conn.close()

    return []


def _execute_action(action_type: str, params: dict, trigger_item: dict) -> str:
    """Execute the action for a triggered rule."""
    try:
        if action_type == "notify":
            from backend.heartbeat.engine import _push_notification
            title = params.get("title", "Workflow Alert")
            body = params.get("body_template", "{item}").format(item=str(trigger_item))
            _push_notification(title, body, params.get("priority", "normal"))
            return "notification_sent"

        elif action_type == "create_reminder":
            from backend.storage.database import save_reminder
            text = params.get("text_template", "Follow up: {item}").format(item=str(trigger_item))
            save_reminder("workflow", text)
            return "reminder_created"

        elif action_type == "flag_inbox":
            # Items flagged via trigger are already in relevant tables
            return "flagged"

        return f"unknown_action:{action_type}"

    except Exception as e:
        logger.warning("Workflow action failed: %s", e)
        return f"error:{e}"


def get_workflow_log(limit: int = 50) -> list[dict]:
    init_workflow_tables()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_default_rules():
    """Create a set of sensible default workflow rules."""
    init_workflow_tables()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT COUNT(*) as c FROM workflow_rules").fetchone()["c"]
        if existing > 0:
            return
    finally:
        conn.close()

    import json

    defaults = [
        ("Promise due in 2 days", "promise_due_soon", "notify",
         {"days_before": 2}, {"title": "Promise due soon", "priority": "important"}),
        ("Overdue tasks", "task_overdue", "notify",
         {}, {"title": "Overdue task", "priority": "normal"}),
        ("Stale contacts (30 days)", "no_interaction", "notify",
         {"days_threshold": 30}, {"title": "Reconnect reminder", "priority": "normal"}),
        ("Unassigned tasks (24h)", "unassigned_task", "notify",
         {"hours_threshold": 24}, {"title": "Unassigned task", "priority": "normal"}),
    ]

    for name, trigger, action, condition, params in defaults:
        create_rule(name, trigger, action, condition, params)

    logger.info("Created %d default workflow rules", len(defaults))
