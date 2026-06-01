"""Scheduled intelligence runs.

Hooks into the existing APScheduler instance from heartbeat.engine.
Runs intelligence features on a schedule, persists every flag they raise
into flag_outcomes, and notifies the user when a high-priority signal lands.

Schedule:
- 06:30 IST  daily — overload + relationship_decay + customer_pulse + project_risk
                       + silent_projects + bus_factor
- 07:00 IST  daily — anomalies (24h window)
- weekly Mon — recurring_problems (semantic clusters)
- weekly Mon — meeting_roi
- nightly 03:00 — task_age_audit + emerging_topics

Each job records its findings via record_flag(feature, key, payload).
Flags created today won't be re-recorded thanks to the unique constraint.
"""

import logging
from datetime import date

logger = logging.getLogger("sudobrain.intelligence.scheduler")


def _safe(fn, name):
    try:
        return fn()
    except Exception as e:
        logger.error("intelligence job %s failed: %s", name, e)
        return None


def _record_flags(feature: str, items: list[dict], key_fn):
    from backend.intelligence.flag_outcomes import record_flag
    today = date.today().isoformat()
    n = 0
    for item in items:
        try:
            key = f"{key_fn(item)}_{today}"
            record_flag(feature, key, item)
            n += 1
        except Exception:
            pass
    return n


def run_overload_job() -> dict:
    from backend.intelligence.overload import compute_overload
    from backend.intelligence.flag_outcomes import record_flag
    today = date.today().isoformat()
    o = _safe(compute_overload, "overload")
    if not o:
        return {"flagged": 0}
    if o.get("score", 0) >= 60:
        record_flag(
            "overload",
            f"overload_{today}",
            {"score": o["score"], "verdict": o.get("verdict")},
        )
        return {"flagged": 1, "score": o["score"]}
    return {"flagged": 0, "score": o.get("score")}


def run_decay_job() -> dict:
    from backend.intelligence.relationship_decay import compute_relationship_decay
    d = _safe(lambda: compute_relationship_decay(window_days=14), "decay")
    if not d:
        return {"flagged": 0}
    n = _record_flags(
        "relationship_decay",
        [f for f in d.get("flagged", []) if f["trend"] == "cooling"],
        lambda f: f"decay_{f['name']}",
    )
    return {"flagged": n}


def run_customer_pulse_job() -> dict:
    from backend.intelligence.customer_pulse import compute_customer_pulse
    p = _safe(compute_customer_pulse, "customer_pulse")
    if not p:
        return {"flagged": 0}
    flagged = [
        o for o in p.get("organizations", [])
        if o["status"] in ("going_quiet", "cooling")
    ]
    n = _record_flags("customer_pulse", flagged, lambda o: f"pulse_{o['domain']}")
    return {"flagged": n}


def run_project_risk_job() -> dict:
    from backend.intelligence.project_risk import compute_project_risk
    r = _safe(compute_project_risk, "project_risk")
    if not r:
        return {"flagged": 0}
    flagged = (r.get("critical") or []) + (r.get("at_risk") or [])
    n = _record_flags(
        "project_risk", flagged, lambda p: f"risk_{p['project'].replace(' ', '_')}"
    )
    return {"flagged": n}


def run_silent_projects_job() -> dict:
    from backend.intelligence.silent_projects import compute_silent_projects
    s = _safe(lambda: compute_silent_projects(threshold_days=14), "silent")
    if not s:
        return {"flagged": 0}
    n = _record_flags(
        "silent_projects",
        s.get("flagged", []),
        lambda p: f"silent_{p['project'].replace(' ', '_')}",
    )
    return {"flagged": n}


def run_bus_factor_job() -> dict:
    from backend.intelligence.bus_factor import compute_bus_factor
    b = _safe(compute_bus_factor, "bus_factor")
    if not b:
        return {"flagged": 0}
    n = _record_flags(
        "bus_factor",
        b.get("high_risk", []),
        lambda p: f"bus_{p['project'].replace(' ', '_')}",
    )
    return {"flagged": n}


def run_anomalies_job() -> dict:
    from backend.intelligence.anomalies import compute_anomalies
    a = _safe(lambda: compute_anomalies(days=30, sigma=2.0), "anomalies")
    if not a:
        return {"flagged": 0}
    n = _record_flags(
        "anomalies",
        a.get("anomalies", []),
        lambda x: f"anomaly_{x['date']}_{x['metric']}",
    )
    return {"flagged": n}


def run_recurring_job() -> dict:
    from backend.intelligence.recurring_problems import compute_recurring_problems
    r = _safe(lambda: compute_recurring_problems(min_cluster_size=3), "recurring")
    if not r or "clusters" not in r:
        return {"flagged": 0}
    big = [c for c in r["clusters"] if c["cluster_size"] >= 4]
    n = _record_flags(
        "recurring_problems",
        big,
        lambda c: f"cluster_size{c['cluster_size']}_{date.today().isoformat()}",
    )
    return {"flagged": n}


def run_task_age_job() -> dict:
    from backend.intelligence.task_age_audit import compute_task_age_audit
    t = _safe(lambda: compute_task_age_audit(threshold_days=30), "task_age")
    if not t:
        return {"flagged": 0}
    items = t.get("old_urgent", []) + t.get("heavily_overdue", [])
    n = _record_flags(
        "task_age", items, lambda i: f"task_{i.get('id', i.get('text','')[:20])}"
    )
    return {"flagged": n}


def run_emerging_topics_job() -> dict:
    from backend.intelligence.emerging_topics import compute_emerging_topics
    e = _safe(lambda: compute_emerging_topics(window_days=7), "emerging")
    if not e:
        return {"flagged": 0}
    items = [t for t in e.get("emerging_terms", []) if t.get("recent_count", 0) >= 5]
    n = _record_flags("emerging_topics", items, lambda t: f"emerge_{t['term']}")
    return {"flagged": n}


def run_meeting_roi_job() -> dict:
    from backend.intelligence.meeting_roi import compute_meeting_roi
    m = _safe(lambda: compute_meeting_roi(days=30), "meeting_roi")
    if not m:
        return {"flagged": 0}
    n = _record_flags(
        "meeting_roi",
        m.get("low_roi_meetings", []),
        lambda mt: f"lowroi_{mt['recording_id']}",
    )
    return {"flagged": n}


# === Composite jobs ===

def run_morning_intelligence() -> dict:
    """Composite morning run: overload + decay + customer + project + silent + bus."""
    return {
        "overload": run_overload_job(),
        "relationship_decay": run_decay_job(),
        "customer_pulse": run_customer_pulse_job(),
        "project_risk": run_project_risk_job(),
        "silent_projects": run_silent_projects_job(),
        "bus_factor": run_bus_factor_job(),
        "anomalies": run_anomalies_job(),
    }


def run_nightly_intelligence() -> dict:
    return {
        "task_age": run_task_age_job(),
        "emerging_topics": run_emerging_topics_job(),
    }


def run_weekly_intelligence() -> dict:
    return {
        "recurring_problems": run_recurring_job(),
        "meeting_roi": run_meeting_roi_job(),
    }


def run_all_intelligence() -> dict:
    """Run every intelligence job once. Used for manual /trigger and tests."""
    return {
        **run_morning_intelligence(),
        **run_nightly_intelligence(),
        **run_weekly_intelligence(),
    }


def register_jobs(scheduler):
    """Add intelligence jobs to an existing APScheduler instance."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        run_morning_intelligence,
        trigger=CronTrigger(hour=6, minute=30),
        id="intelligence_morning",
        misfire_grace_time=600,
        replace_existing=True,
    )
    scheduler.add_job(
        run_nightly_intelligence,
        trigger=CronTrigger(hour=3, minute=0),
        id="intelligence_nightly",
        misfire_grace_time=600,
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekly_intelligence,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="intelligence_weekly",
        misfire_grace_time=600,
        replace_existing=True,
    )
    logger.info("intelligence jobs registered (morning 06:30, nightly 03:00, weekly Mon 07:00)")
