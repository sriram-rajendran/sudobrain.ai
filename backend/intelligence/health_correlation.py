"""Habit & health correlation — connect habits/health data to productivity patterns.

Analyzes correlations between habit streaks, sleep, exercise and
meeting effectiveness, decisions made, tasks completed.
"""

import logging
from datetime import date, timedelta
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.health")


def get_habit_productivity_correlation(days: int = 30) -> dict:
    """Correlate habit completion with productivity metrics.

    For each day in the period, pairs:
    - habits completed (from habit_log)
    - meetings held
    - decisions made
    - tasks completed
    - meeting sentiment (if available)

    Returns daily data + correlation insights.
    """
    conn = get_connection()
    try:
        start = (date.today() - timedelta(days=days)).isoformat()
        daily_data = {}

        # Initialize days
        for i in range(days):
            d = (date.today() - timedelta(days=i)).isoformat()
            daily_data[d] = {
                "date": d,
                "habits_completed": 0,
                "meetings": 0,
                "decisions": 0,
                "tasks_completed": 0,
                "sentiment": None,
            }

        # Habit completions per day
        try:
            rows = conn.execute(
                """SELECT date(logged_at) as d, COUNT(*) as c FROM habit_log
                WHERE completed = TRUE AND logged_at >= ? GROUP BY d""",
                (start,),
            ).fetchall()
            for r in rows:
                if r["d"] in daily_data:
                    daily_data[r["d"]]["habits_completed"] = r["c"]
        except Exception:
            pass

        # Meetings per day
        try:
            rows = conn.execute(
                """SELECT date(created_at) as d, COUNT(*) as c FROM recordings
                WHERE status = 'completed' AND created_at >= ? GROUP BY d""",
                (start,),
            ).fetchall()
            for r in rows:
                if r["d"] in daily_data:
                    daily_data[r["d"]]["meetings"] = r["c"]
        except Exception:
            pass

        # Decisions per day
        try:
            rows = conn.execute(
                """SELECT date(created_at) as d, COUNT(*) as c FROM decisions
                WHERE created_at >= ? GROUP BY d""",
                (start,),
            ).fetchall()
            for r in rows:
                if r["d"] in daily_data:
                    daily_data[r["d"]]["decisions"] = r["c"]
        except Exception:
            pass

        # Sentiment per day
        try:
            rows = conn.execute(
                """SELECT date(created_at) as d, AVG(sentiment_score) as avg_s
                FROM meeting_sentiment WHERE created_at >= ? GROUP BY d""",
                (start,),
            ).fetchall()
            for r in rows:
                if r["d"] in daily_data:
                    daily_data[r["d"]]["sentiment"] = round(r["avg_s"], 2) if r["avg_s"] else None
        except Exception:
            pass

    finally:
        conn.close()

    daily_list = sorted(daily_data.values(), key=lambda x: x["date"])

    # Compute simple correlation insights
    insights = _compute_insights(daily_list)

    return {
        "period_days": days,
        "daily_data": daily_list,
        "insights": insights,
    }


def _compute_insights(daily_data: list[dict]) -> list[str]:
    """Generate human-readable correlation insights."""
    if len(daily_data) < 7:
        return ["Not enough data for insights (need at least 7 days)"]

    insights = []

    # Days with habits vs without
    habit_days = [d for d in daily_data if d["habits_completed"] > 0]
    no_habit_days = [d for d in daily_data if d["habits_completed"] == 0]

    if habit_days and no_habit_days:
        avg_decisions_with = sum(d["decisions"] for d in habit_days) / len(habit_days)
        avg_decisions_without = sum(d["decisions"] for d in no_habit_days) / len(no_habit_days)

        if avg_decisions_with > avg_decisions_without * 1.2:
            pct = round((avg_decisions_with / max(avg_decisions_without, 0.1) - 1) * 100)
            insights.append(
                f"On days you complete habits, you make {pct}% more decisions "
                f"({avg_decisions_with:.1f} vs {avg_decisions_without:.1f})"
            )

        avg_meetings_with = sum(d["meetings"] for d in habit_days) / len(habit_days)
        avg_meetings_without = sum(d["meetings"] for d in no_habit_days) / len(no_habit_days)

        if avg_meetings_with > avg_meetings_without:
            insights.append(
                f"Habit days correlate with more meetings ({avg_meetings_with:.1f} vs {avg_meetings_without:.1f})"
            )

    # Sentiment on habit days vs non-habit days
    sent_with = [d["sentiment"] for d in habit_days if d.get("sentiment") is not None]
    sent_without = [d["sentiment"] for d in no_habit_days if d.get("sentiment") is not None]

    if sent_with and sent_without:
        avg_sent_with = sum(sent_with) / len(sent_with)
        avg_sent_without = sum(sent_without) / len(sent_without)

        if avg_sent_with > avg_sent_without:
            insights.append(
                f"Meeting sentiment is more positive on habit days "
                f"({avg_sent_with:.2f} vs {avg_sent_without:.2f})"
            )

    if not insights:
        insights.append("No strong correlations found yet — keep logging habits for better insights")

    return insights


def store_health_data(data_type: str, value: float, date_str: str = None):
    """Store health data (sleep hours, steps, etc.) from HealthKit or manual entry.

    This endpoint can be called from the Swift app after reading HealthKit data.
    """
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS health_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_type TEXT NOT NULL,
                value REAL NOT NULL,
                date TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO health_data (data_type, value, date) VALUES (?, ?, ?)",
            (data_type, value, date_str or date.today().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
