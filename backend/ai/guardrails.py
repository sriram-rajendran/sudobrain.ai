"""Guardrails — 4-tier permission system for SudoBrain actions."""

import json
import sqlite3
from datetime import datetime
from enum import IntEnum
from typing import Optional

from backend.storage.database import get_connection


class Tier(IntEnum):
    AUTO = 0       # Reads, search, analysis — no approval needed
    SOFT = 1       # Create reminders, tag knowledge — do it, notify, user can undo
    HARD = 2       # Draft outbound changes or proposals; wait for approval
    FORBIDDEN = 3  # Delete data, share externally — always refused


# Action classification
ACTION_TIERS = {
    # Tier 0 — Auto
    "search": Tier.AUTO,
    "read_transcript": Tier.AUTO,
    "read_recording": Tier.AUTO,
    "generate_summary": Tier.AUTO,
    "generate_briefing": Tier.AUTO,
    "compute_insights": Tier.AUTO,
    "heartbeat_check": Tier.AUTO,
    "process_audio": Tier.AUTO,
    "extract_knowledge": Tier.AUTO,

    # Tier 1 — Soft
    "create_reminder": Tier.SOFT,
    "create_task": Tier.SOFT,
    "update_people_graph": Tier.SOFT,
    "tag_knowledge": Tier.SOFT,
    "log_habit": Tier.SOFT,
    "log_expense": Tier.SOFT,
    "save_idea": Tier.SOFT,

    # Tier 2 — Hard
    "draft_email": Tier.HARD,
    "draft_message": Tier.HARD,
    "propose_calendar_event": Tier.HARD,
    "complete_task": Tier.HARD,
    "update_standing_orders": Tier.HARD,
    "execute_shell": Tier.HARD,

    # Tier 3 — Forbidden
    "delete_recording": Tier.FORBIDDEN,
    "delete_transcript": Tier.FORBIDDEN,
    "delete_person": Tier.FORBIDDEN,
    "share_externally": Tier.FORBIDDEN,
    "modify_soul": Tier.FORBIDDEN,
    "disable_security": Tier.FORBIDDEN,
}


def init_action_log():
    """Create the action_log table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            tier INTEGER NOT NULL,
            description TEXT,
            details_json TEXT,
            status TEXT DEFAULT 'pending',
            approved_at DATETIME,
            executed_at DATETIME,
            result TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def init_system_control():
    """Create local system-control flags used by safety controls."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_control (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            reason TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def is_emergency_stop_active() -> bool:
    """Return True when mutating/proactive activity should stay paused."""
    init_system_control()
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM system_control WHERE key = 'emergency_stop'").fetchone()
        return bool(row and row["value"] == "active")
    finally:
        conn.close()


def _reject_pending_for_emergency(reason: str) -> int:
    init_action_log()
    conn = get_connection()
    try:
        result = conn.execute(
            """UPDATE action_log
            SET status = 'rejected', result = ?
            WHERE status = 'pending'""",
            (f"Rejected by emergency stop: {reason}",),
        )
        conn.commit()
        return result.rowcount
    finally:
        conn.close()


def set_emergency_stop(active: bool, reason: str = None) -> dict:
    """Persist or clear the emergency stop flag."""
    init_system_control()
    reason_text = reason or ("Emergency stop enabled" if active else "Resumed by user")
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO system_control (key, value, reason, updated_at)
            VALUES ('emergency_stop', ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at""",
            ("active" if active else "inactive", reason_text, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    rejected = _reject_pending_for_emergency(reason_text) if active else 0
    return get_system_control_status(extra={"rejected_pending_actions": rejected})


def get_system_control_status(extra: dict = None) -> dict:
    """Return safety-control state and guardrail queue counts."""
    init_action_log()
    init_system_control()
    conn = get_connection()
    try:
        row = conn.execute("SELECT value, reason, updated_at FROM system_control WHERE key = 'emergency_stop'").fetchone()
        pending = conn.execute("SELECT COUNT(*) AS c FROM action_log WHERE status = 'pending'").fetchone()["c"]
        approved = conn.execute("SELECT COUNT(*) AS c FROM action_log WHERE status = 'approved'").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) AS c FROM action_log WHERE status = 'rejected'").fetchone()["c"]
    finally:
        conn.close()

    status = {
        "emergency_stop": {
            "active": bool(row and row["value"] == "active"),
            "reason": row["reason"] if row else None,
            "updated_at": row["updated_at"] if row else None,
        },
        "guardrails": {
            "pending_actions": pending,
            "approved_actions": approved,
            "rejected_actions": rejected,
        },
    }
    if extra:
        status.update(extra)
    return status


def check_permission(action_type: str) -> dict:
    """Check if an action is allowed.

    Returns:
        {
            "allowed": bool,
            "tier": int,
            "requires_approval": bool,
            "message": str
        }
    """
    tier = ACTION_TIERS.get(action_type, Tier.HARD)  # Default to HARD for unknown actions

    if tier == Tier.AUTO:
        return {
            "allowed": True,
            "tier": tier,
            "requires_approval": False,
            "message": "Auto-approved",
        }
    elif tier == Tier.SOFT:
        return {
            "allowed": True,
            "tier": tier,
            "requires_approval": False,
            "message": "Soft-approved. User will be notified.",
        }
    elif tier == Tier.HARD:
        return {
            "allowed": False,
            "tier": tier,
            "requires_approval": True,
            "message": "Requires explicit approval before execution.",
        }
    else:  # FORBIDDEN
        return {
            "allowed": False,
            "tier": tier,
            "requires_approval": False,
            "message": f"Action '{action_type}' is forbidden. Cannot be executed.",
        }


def log_action(action_type: str, description: str, details: dict = None, status: str = "auto_approved") -> int:
    """Log an action to the audit trail. Returns the action ID."""
    init_action_log()
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO action_log (action_type, tier, description, details_json, status, executed_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            action_type,
            int(ACTION_TIERS.get(action_type, Tier.HARD)),
            description,
            json.dumps(details) if details else None,
            status,
            datetime.now().isoformat() if status in ("auto_approved", "approved") else None,
        ),
    )
    action_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return action_id


def request_approval(action_type: str, description: str, details: dict = None) -> int:
    """Create a pending approval request. Returns the action ID."""
    init_action_log()
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO action_log (action_type, tier, description, details_json, status)
        VALUES (?, ?, ?, ?, 'pending')""",
        (
            action_type,
            int(ACTION_TIERS.get(action_type, Tier.HARD)),
            description,
            json.dumps(details) if details else None,
        ),
    )
    action_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return action_id


def approve_action(action_id: int) -> bool:
    """Approve a pending action."""
    conn = get_connection()
    result = conn.execute(
        "UPDATE action_log SET status = 'approved', approved_at = ? WHERE id = ? AND status = 'pending'",
        (datetime.now().isoformat(), action_id),
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0


def reject_action(action_id: int) -> bool:
    """Reject a pending action."""
    conn = get_connection()
    result = conn.execute(
        "UPDATE action_log SET status = 'rejected' WHERE id = ? AND status = 'pending'",
        (action_id,),
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0


def get_pending_actions() -> list:
    """Get all pending approval requests."""
    init_action_log()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM action_log WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def execute_action(action_type: str, description: str, details: dict = None) -> dict:
    """Execute an action through the guardrails system.

    Returns:
        {
            "executed": bool,
            "action_id": int,
            "status": str,
            "message": str
        }
    """
    permission = check_permission(action_type)

    if is_emergency_stop_active() and permission["tier"] != Tier.AUTO:
        action_id = log_action(action_type, description, details, status="rejected")
        return {
            "executed": False,
            "action_id": action_id,
            "status": "emergency_stopped",
            "message": "Emergency stop is active. Mutating actions are paused until resumed.",
        }

    if permission["tier"] == Tier.FORBIDDEN:
        action_id = log_action(action_type, description, details, status="forbidden")
        return {
            "executed": False,
            "action_id": action_id,
            "status": "forbidden",
            "message": permission["message"],
        }

    if permission["tier"] == Tier.HARD:
        action_id = request_approval(action_type, description, details)
        return {
            "executed": False,
            "action_id": action_id,
            "status": "pending_approval",
            "message": "Action queued for approval.",
        }

    # Auto or Soft — execute immediately
    action_id = log_action(action_type, description, details, status="auto_approved")
    return {
        "executed": True,
        "action_id": action_id,
        "status": "executed",
        "message": permission["message"],
    }
