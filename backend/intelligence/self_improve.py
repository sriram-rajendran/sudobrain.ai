"""Self-Improving Rules — learn from user corrections, store as persistent rules."""

import os
import re
from datetime import datetime
from pathlib import Path
from backend.storage.database import get_connection
from backend.ai.local_llm_engine import ask

RULES_PATH = Path.home() / ".sudobrain" / "workspace" / "RULES.md"


def init_rules_tables():
    """Create learned rules tables."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS learned_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text TEXT NOT NULL,
            category TEXT,
            source TEXT DEFAULT 'explicit_correction',
            confidence REAL DEFAULT 1.0,
            observation_count INTEGER DEFAULT 1,
            last_applied DATETIME,
            last_reinforced DATETIME,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS correction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_output TEXT,
            corrected_output TEXT,
            context TEXT,
            rule_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.executescript("""
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS category TEXT;
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'explicit_correction';
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 1.0;
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS observation_count INTEGER DEFAULT 1;
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS last_applied TIMESTAMP;
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS last_reinforced TIMESTAMP;
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
        ALTER TABLE learned_rules ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;
    """)
    conn.commit()
    conn.close()


def detect_correction(user_message: str) -> dict:
    """Detect if a user message is a correction.

    Returns: {"is_correction": bool, "rule": str, "category": str}
    """
    correction_patterns = [
        r"no,?\s+(it\s+)?should\s+be",
        r"change\s+that\s+to",
        r"don'?t\s+(do|use|say|add|include)",
        r"always\s+use",
        r"i\s+prefer",
        r"that'?s\s+wrong",
        r"next\s+time,?\s+(do|use|please)",
        r"not\s+like\s+that",
        r"stop\s+(doing|using|adding)",
    ]

    is_correction = any(re.search(p, user_message.lower()) for p in correction_patterns)

    if not is_correction:
        return {"is_correction": False}

    # Use local reasoning engine to extract the generalizable rule
    prompt = f"""The user said: "{user_message}"

This appears to be a correction or preference. Extract a generalizable rule from it.

Return JSON:
{{
  "rule": "the rule to follow going forward (imperative form, e.g., 'Use 24-hour time format')",
  "category": "formatting or people or language or workflow or notification"
}}

Return ONLY valid JSON."""

    response = ask(prompt, max_wait=30)

    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        result = __import__("json").loads(cleaned)
        return {
            "is_correction": True,
            "rule": result.get("rule", user_message),
            "category": result.get("category", "general"),
        }
    except Exception:
        return {
            "is_correction": True,
            "rule": user_message,
            "category": "general",
        }


def save_rule(rule_text: str, category: str = "general", source: str = "explicit_correction",
              original: str = None, corrected: str = None, context: str = None) -> int:
    """Save a learned rule. Returns rule ID."""
    init_rules_tables()
    conn = get_connection()

    # Check if similar rule already exists
    existing = conn.execute(
        "SELECT id, observation_count FROM learned_rules WHERE LOWER(rule_text) = LOWER(?)",
        (rule_text,),
    ).fetchone()

    if existing:
        # Reinforce existing rule
        conn.execute(
            "UPDATE learned_rules SET observation_count = observation_count + 1, last_reinforced = ? WHERE id = ?",
            (datetime.now().isoformat(), existing["id"]),
        )
        rule_id = existing["id"]
    else:
        # Create new rule
        cursor = conn.execute(
            "INSERT INTO learned_rules (rule_text, category, source) VALUES (?, ?, ?)",
            (rule_text, category, source),
        )
        rule_id = cursor.lastrowid

    # Log the correction
    if original or corrected:
        conn.execute(
            "INSERT INTO correction_log (original_output, corrected_output, context, rule_id) VALUES (?, ?, ?, ?)",
            (original, corrected, context, rule_id),
        )

    conn.commit()
    conn.close()

    # Update RULES.md file
    _update_rules_file()

    return rule_id


def get_all_rules(status: str = "active") -> list:
    """Get all learned rules."""
    init_rules_tables()
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM learned_rules
        WHERE COALESCE(status, CASE WHEN active THEN 'active' ELSE 'inactive' END) = ?
        ORDER BY created_at DESC""",
        (status,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_correction_log(limit: int = 20) -> list:
    """Get recent corrections."""
    init_rules_tables()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM correction_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _update_rules_file():
    """Regenerate RULES.md from database rules."""
    rules = get_all_rules()

    content = "# Learned Rules\n\nThis file is auto-updated as SudoBrain learns from user corrections.\n\n"

    # Group by category
    categories = {}
    for r in rules:
        cat = r.get("category", "general")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    for cat, cat_rules in sorted(categories.items()):
        content += f"## {cat.title()}\n"
        for r in cat_rules:
            obs = r.get("observation_count", 1)
            suffix = f" (reinforced {obs}x)" if obs > 1 else ""
            content += f"- {r['rule_text']}{suffix}\n"
        content += "\n"

    RULES_PATH.write_text(content)
    print(f"[Rules] Updated RULES.md with {len(rules)} rules")


def process_chat_for_corrections(user_message: str, ai_response: str) -> dict:
    """Check if the user's message contains a correction and learn from it.

    Called after each chat exchange.
    Returns: {"learned": bool, "rule": str} or {"learned": False}
    """
    detection = detect_correction(user_message)

    if not detection["is_correction"]:
        return {"learned": False}

    rule_id = save_rule(
        rule_text=detection["rule"],
        category=detection.get("category", "general"),
        source="explicit_correction",
        original=ai_response[:200] if ai_response else None,
        corrected=user_message[:200],
        context="chat",
    )

    return {
        "learned": True,
        "rule": detection["rule"],
        "rule_id": rule_id,
        "message": f"Learned: {detection['rule']}. Will apply this going forward.",
    }
