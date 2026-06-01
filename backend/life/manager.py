"""Daily Life Manager — habits, expenses, ideas."""

from datetime import datetime, date
from backend.storage.database import get_connection


def init_life_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            target_frequency TEXT DEFAULT 'daily',
            active BOOLEAN DEFAULT TRUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER REFERENCES habits(id),
            date DATE NOT NULL,
            completed BOOLEAN DEFAULT TRUE,
            duration_minutes REAL,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(habit_id, date)
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'INR',
            category TEXT,
            description TEXT,
            date DATE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            context TEXT,
            category TEXT,
            status TEXT DEFAULT 'parked',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# ── Habits ──

def create_habit(name: str, category: str = None, target: str = "daily") -> int:
    init_life_tables()
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO habits (name, category, target_frequency) VALUES (?, ?, ?)",
        (name, category, target),
    )
    hid = cursor.lastrowid
    conn.commit()
    conn.close()
    return hid


def log_habit(habit_id: int, completed: bool = True, note: str = None):
    init_life_tables()
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO habit_logs (habit_id, date, completed, note) VALUES (?, ?, ?, ?)",
        (habit_id, date.today().isoformat(), completed, note),
    )
    conn.commit()
    conn.close()


def get_habits_with_streaks() -> list:
    init_life_tables()
    conn = get_connection()
    habits = conn.execute("SELECT * FROM habits WHERE active = TRUE ORDER BY name").fetchall()
    result = []
    for h in habits:
        logs = conn.execute(
            "SELECT date, completed FROM habit_logs WHERE habit_id = ? ORDER BY date DESC LIMIT 7",
            (h["id"],),
        ).fetchall()
        streak = 0
        for log in logs:
            if log["completed"]:
                streak += 1
            else:
                break
        total_logged = conn.execute(
            "SELECT COUNT(*) as c FROM habit_logs WHERE habit_id = ? AND completed = TRUE",
            (h["id"],),
        ).fetchone()["c"]
        result.append({**dict(h), "streak": streak, "total_logged": total_logged, "recent_logs": [dict(l) for l in logs]})
    conn.close()
    return result


# ── Expenses ──

def add_expense(amount: float, category: str = None, description: str = None, expense_date: str = None) -> int:
    init_life_tables()
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO expenses (amount, category, description, date) VALUES (?, ?, ?, ?)",
        (amount, category, description, expense_date or date.today().isoformat()),
    )
    eid = cursor.lastrowid
    conn.commit()
    conn.close()
    return eid


def get_expenses(month: str = None) -> list:
    init_life_tables()
    conn = get_connection()
    if month:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date DESC",
            (f"{month}%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM expenses ORDER BY date DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_expense_summary(month: str = None) -> dict:
    init_life_tables()
    conn = get_connection()
    if month:
        rows = conn.execute(
            "SELECT category, SUM(amount) as total FROM expenses WHERE date LIKE ? GROUP BY category",
            (f"{month}%",),
        ).fetchall()
        total = conn.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE date LIKE ?",
            (f"{month}%",),
        ).fetchone()
    else:
        rows = conn.execute("SELECT category, SUM(amount) as total FROM expenses GROUP BY category").fetchall()
        total = conn.execute("SELECT SUM(amount) as total FROM expenses").fetchone()
    conn.close()
    return {
        "total": total["total"] or 0,
        "by_category": {r["category"] or "uncategorized": r["total"] for r in rows},
    }


# ── Ideas ──

def add_idea(text: str, context: str = None, category: str = None) -> int:
    init_life_tables()
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO ideas (text, context, category) VALUES (?, ?, ?)",
        (text, context, category),
    )
    iid = cursor.lastrowid
    conn.commit()
    conn.close()
    return iid


def get_ideas(status: str = None) -> list:
    init_life_tables()
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM ideas WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM ideas ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_idea_status(idea_id: int, status: str) -> bool:
    conn = get_connection()
    result = conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea_id))
    conn.commit()
    conn.close()
    return result.rowcount > 0
