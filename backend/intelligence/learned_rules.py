"""Self-improvement from user corrections.

Captures user overrides of extracted items (wrong assignee, wrong project,
misclassified as action vs decision) and distills them into learned rules
that are injected into future extraction prompts.

Schema:
  user_corrections(id, entity_type, entity_id, field, old_value, new_value,
                   explanation, applied_to_rules, created_at)

  learned_rules(id, rule_text, source_correction_ids, active, created_at)

Flow:
  1. User corrects an action_item.assignee via PATCH
  2. record_correction() logs it
  3. Nightly job (or manual) calls compile_rules() which clusters similar
     corrections and writes a rule
  4. Rules are surfaced via get_active_rules() and included in prompts
"""

import json
from datetime import datetime, timezone
from backend.storage.database import get_connection


def init_tables():
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_corrections (
                id SERIAL PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                explanation TEXT,
                applied_to_rules BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_corr_type ON user_corrections(entity_type);
            CREATE INDEX IF NOT EXISTS idx_corr_applied ON user_corrections(applied_to_rules);

            CREATE TABLE IF NOT EXISTS learned_rules (
                id SERIAL PRIMARY KEY,
                rule_text TEXT NOT NULL,
                source_correction_ids TEXT,
                active BOOLEAN DEFAULT TRUE,
                priority INTEGER DEFAULT 5,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_correction(entity_type: str, entity_id: str, field: str,
                      old_value: str, new_value: str,
                      explanation: str | None = None) -> int:
    init_tables()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO user_corrections
            (entity_type, entity_id, field, old_value, new_value, explanation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entity_type, entity_id, field, old_value, new_value, explanation),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def compile_rules_from_corrections(min_cluster_size: int = 2) -> dict:
    """Look for repeated field→new_value corrections and promote them to rules.

    Naive version: group corrections by (entity_type, field, new_value) and
    when >=min_cluster_size share the same fix, emit a rule.
    """
    init_tables()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT entity_type, field, new_value,
                   array_agg(id) AS ids,
                   array_agg(old_value) AS old_values,
                   COUNT(*) AS c
            FROM user_corrections
            WHERE applied_to_rules = FALSE
            GROUP BY entity_type, field, new_value
            HAVING COUNT(*) >= ?
            """,
            (min_cluster_size,),
        ).fetchall()

        created = 0
        for r in rows:
            rule = (
                f"When extracting {r['entity_type']}.{r['field']}, prefer "
                f"'{r['new_value']}' when the source text mentions one of the "
                f"following (based on user corrections): {r['old_values']}"
            )
            conn.execute(
                "INSERT INTO learned_rules (rule_text, source_correction_ids) VALUES (?, ?)",
                (rule, json.dumps([int(i) for i in r["ids"]])),
            )
            conn.execute(
                "UPDATE user_corrections SET applied_to_rules = TRUE WHERE id = ANY(?)",
                (r["ids"],),
            )
            created += 1
        conn.commit()
    finally:
        conn.close()
    return {"rules_created": created}


def get_active_rules(limit: int = 20) -> list[dict]:
    init_tables()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, rule_text, priority, created_at FROM learned_rules "
            "WHERE active = TRUE ORDER BY priority DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


def rules_prompt_block() -> str:
    """Format active rules for injection into extraction prompts."""
    rules = get_active_rules(limit=10)
    if not rules:
        return ""
    lines = ["LEARNED USER PREFERENCES (apply these rules):"]
    for r in rules:
        lines.append(f"- {r['rule_text']}")
    return "\n".join(lines)
