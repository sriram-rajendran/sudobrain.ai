"""Commit-risk predictor — probability a new commitment will be delivered on time.

Inputs: commitment text + optional due_date
Base: overload score → inverse capacity
Modifiers:
  - historical fulfillment rate (from promises)
  - closer deadlines = higher risk
  - more urgent-open tasks = higher risk
  - assignee overlap (if text mentions a specific project with many open tickets)
"""

import json
import os
from datetime import date, datetime
from backend.intelligence.overload import compute_overload


def _topic_keywords() -> dict[str, float]:
    raw = os.getenv("SUDOBRAIN_COMMIT_RISK_KEYWORDS_JSON", "{}") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result = {}
    for keyword, modifier in parsed.items():
        try:
            result[str(keyword).lower()] = float(modifier)
        except (TypeError, ValueError):
            continue
    return result


def predict_commit_risk(text: str, due_date: str | None = None) -> dict:
    """Return risk (0-1), verdict, reasons."""
    ov = compute_overload()
    if "error" in ov:
        return {"risk": 0.5, "verdict": "unknown", "reasons": ["no self data"]}

    overload_score = ov["score"]  # 0-100
    base_risk = overload_score / 100.0  # start from current load

    reasons = []

    # Factor 1: current load
    reasons.append(
        f"base risk {round(base_risk*100)}% from overload score {overload_score}"
    )

    # Factor 2: deadline tightness
    days_until = None
    if due_date:
        try:
            d = date.fromisoformat(due_date) if len(due_date) == 10 else datetime.fromisoformat(due_date).date()
            days_until = (d - date.today()).days
        except Exception:
            days_until = None

    deadline_modifier = 0.0
    if days_until is not None:
        if days_until < 0:
            deadline_modifier = 0.40
            reasons.append(f"due date already passed (+40%)")
        elif days_until == 0:
            deadline_modifier = 0.30
            reasons.append(f"due today (+30%)")
        elif days_until <= 2:
            deadline_modifier = 0.20
            reasons.append(f"due in {days_until}d (+20%)")
        elif days_until <= 7:
            deadline_modifier = 0.10
            reasons.append(f"due in {days_until}d (+10%)")
        else:
            reasons.append(f"due in {days_until}d (no deadline penalty)")
    else:
        reasons.append("no due date specified")

    # Factor 3: historical fulfillment rate (inverse)
    fulfillment = ov["factors"]["low_fulfillment"]["value"]  # actual rate 0-1
    # If no history, assume 70% (industry baseline)
    if ov["factors"]["low_fulfillment"]["description"].startswith("no "):
        fulfillment = 0.7
    history_modifier = (1.0 - fulfillment) * 0.3
    reasons.append(
        f"historical fulfillment {round(fulfillment*100)}% (+{round(history_modifier*100)}%)"
    )

    # Factor 4: topic-specific load (does the text mention a project that's already overloaded?)
    topic_modifier = 0.0
    text_lower = (text or "").lower()
    hot_keywords = _topic_keywords()
    for kw, mod in hot_keywords.items():
        if kw in text_lower:
            topic_modifier += mod
            reasons.append(f"mentions '{kw}' (+{round(mod*100)}%)")

    risk = min(1.0, base_risk * 0.5 + deadline_modifier + history_modifier + topic_modifier)
    risk = round(risk, 2)

    if risk >= 0.8:
        verdict = "very high risk — decline or renegotiate"
    elif risk >= 0.6:
        verdict = "high risk — think twice"
    elif risk >= 0.4:
        verdict = "moderate risk — feasible with tradeoffs"
    elif risk >= 0.2:
        verdict = "low risk — safe to commit"
    else:
        verdict = "very low risk"

    return {
        "risk": risk,
        "verdict": verdict,
        "reasons": reasons,
        "inputs": {
            "text": text,
            "due_date": due_date,
            "days_until": days_until,
            "overload_score": overload_score,
        },
    }
