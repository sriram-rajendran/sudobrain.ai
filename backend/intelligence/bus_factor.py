"""Bus factor — detect knowledge concentration risk.

For each project/topic, rank experts by activity signal:
  - # Linear issues assigned + authored
  - # Slack messages in related channels
  - # decisions made
  - # action items owned

Flags topics where expert_count == 1 (single point of knowledge).
"""

from backend.storage.database import get_connection


def compute_bus_factor() -> dict:
    conn = get_connection()
    try:
        # Build project → experts map from linear_issues
        project_experts: dict[str, dict[str, int]] = {}

        rows = conn.execute(
            "SELECT project_name, assignee_name, COUNT(*) c "
            "FROM linear_issues "
            "WHERE project_name IS NOT NULL AND project_name != '' "
            "  AND assignee_name IS NOT NULL AND assignee_name != '' "
            "GROUP BY project_name, assignee_name"
        ).fetchall()
        for r in rows:
            project_experts.setdefault(r["project_name"], {})
            project_experts[r["project_name"]][r["assignee_name"]] = r["c"]

        # Layer action items (assignees who work on a project)
        rows = conn.execute(
            "SELECT project, assignee, COUNT(*) c "
            "FROM action_items "
            "WHERE project IS NOT NULL AND project != '' "
            "  AND assignee IS NOT NULL AND assignee != '' "
            "GROUP BY project, assignee"
        ).fetchall()
        for r in rows:
            project_experts.setdefault(r["project"], {})
            project_experts[r["project"]][r["assignee"]] = (
                project_experts[r["project"]].get(r["assignee"], 0) + r["c"]
            )

        # Layer decisions
        rows = conn.execute(
            "SELECT project, made_by, COUNT(*) c "
            "FROM decisions "
            "WHERE project IS NOT NULL AND project != '' "
            "  AND made_by IS NOT NULL AND made_by != '' "
            "GROUP BY project, made_by"
        ).fetchall()
        for r in rows:
            project_experts.setdefault(r["project"], {})
            project_experts[r["project"]][r["made_by"]] = (
                project_experts[r["project"]].get(r["made_by"], 0) + r["c"]
            )
    finally:
        conn.close()

    # Compute stats per project
    result = []
    for project, experts in project_experts.items():
        sorted_experts = sorted(experts.items(), key=lambda kv: -kv[1])
        total_activity = sum(experts.values())
        # Bus factor = min people needed to cover 80% of activity
        covered = 0
        bus = 0
        for _, cnt in sorted_experts:
            bus += 1
            covered += cnt
            if covered >= total_activity * 0.8:
                break

        top_expert = sorted_experts[0][0] if sorted_experts else None
        top_share = sorted_experts[0][1] / total_activity if total_activity else 0

        result.append({
            "project": project,
            "expert_count": len(experts),
            "bus_factor": bus,  # how many people cover 80% of work
            "total_activity": total_activity,
            "top_expert": top_expert,
            "top_share_pct": round(top_share * 100, 1),
            "experts": [{"name": n, "activity": c} for n, c in sorted_experts[:5]],
            "risk": "high" if bus == 1 else ("medium" if bus == 2 else "low"),
        })

    result.sort(key=lambda p: (p["bus_factor"], -p["total_activity"]))

    high_risk = [p for p in result if p["risk"] == "high"]
    return {
        "total_projects": len(result),
        "high_risk_count": len(high_risk),
        "high_risk": high_risk[:15],
        "all_projects": result,
    }
