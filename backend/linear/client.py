"""Linear client — direct GraphQL API. READ-ONLY.

Uses a Personal API Key. No OAuth needed.
Fetches issues, comments, projects, teams, members in seconds.
"""

import logging
import os
import requests
from datetime import datetime, timedelta

logger = logging.getLogger("sudobrain.linear")

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TOKEN = os.getenv("LINEAR_API_TOKEN", "")


def _headers() -> dict:
    token = LINEAR_TOKEN or os.getenv("LINEAR_API_TOKEN", "")
    if not token:
        raise ValueError("LINEAR_API_TOKEN not set in .env")
    return {"Authorization": token, "Content-Type": "application/json"}


def _query(gql: str, variables: dict = None, timeout: int = 30) -> dict:
    """Execute a GraphQL query and return data."""
    payload = {"query": gql}
    if variables:
        payload["variables"] = variables

    resp = requests.post(LINEAR_API_URL, json=payload, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    result = resp.json()

    if "errors" in result:
        logger.error("Linear GraphQL errors: %s", result["errors"])
        raise RuntimeError(f"Linear API error: {result['errors']}")

    return result.get("data", {})


def is_available() -> bool:
    try:
        data = _query("{ viewer { id } }")
        return bool(data.get("viewer", {}).get("id"))
    except Exception:
        return False


def get_viewer() -> dict:
    data = _query("{ viewer { id name email } }")
    return data.get("viewer", {})


def get_teams() -> list[dict]:
    data = _query("{ teams { nodes { id name key description } } }")
    return data.get("teams", {}).get("nodes", [])


def get_members() -> list[dict]:
    data = _query("""
    {
      users { nodes { id name email displayName active } }
    }
    """)
    return [u for u in data.get("users", {}).get("nodes", []) if u.get("active")]


def get_issues(days: int = 30, include_done: bool = False) -> list[dict]:
    """Fetch issues updated in the last N days. Paginates until exhausted.

    If days <= 0, fetches ALL issues (no date filter).
    If include_done is True, includes cancelled/completed issues.
    """
    filter_parts = []
    if days and days > 0:
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        filter_parts.append(f'updatedAt: {{ gte: "{since}" }}')
    if not include_done:
        filter_parts.append('state: { type: { nin: ["cancelled"] } }')
    filter_block = f"filter: {{ {' '.join(filter_parts)} }}" if filter_parts else ""

    issues: list[dict] = []
    cursor: str | None = None

    while True:
        after = f', after: "{cursor}"' if cursor else ""
        query = f"""
        {{
          issues(
            first: 250{after}
            {filter_block}
            orderBy: updatedAt
          ) {{
            nodes {{
              id
              title
              description
              priority
              priorityLabel
              state {{ id name type color }}
              assignee {{ id name email }}
              creator {{ id name email }}
              team {{ id name key }}
              project {{ id name }}
              cycle {{ id name number }}
              labels {{ nodes {{ name color }} }}
              dueDate
              completedAt
              canceledAt
              createdAt
              updatedAt
              url
              parent {{ id title }}
              comments {{ nodes {{ id body user {{ name email }} createdAt }} }}
            }}
            pageInfo {{ hasNextPage endCursor }}
          }}
        }}
        """
        try:
            data = _query(query, timeout=60)
        except Exception as e:
            logger.error("get_issues failed: %s", e)
            break

        block = data.get("issues", {})
        issues.extend(block.get("nodes", []))
        pi = block.get("pageInfo", {}) or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")

    logger.info("Linear: fetched %d issues (paginated)", len(issues))
    return issues


def get_projects() -> list[dict]:
    """Fetch all projects."""
    query = """
    {
      projects(first: 100) {
        nodes {
          id name description
          state
          startDate
          targetDate
          progress
          lead { id name email }
        }
      }
    }
    """
    try:
        data = _query(query)
        return data.get("projects", {}).get("nodes", [])
    except Exception as e:
        logger.error("get_projects failed: %s", e)
        return []


def get_cycles(team_id: str = None) -> list[dict]:
    """Fetch active/recent cycles (sprints)."""
    team_filter = f'teamId: {{ eq: "{team_id}" }}' if team_id else ""
    query = f"""
    {{
      cycles(
        first: 10
        filter: {{ {team_filter} }}
        orderBy: createdAt
      ) {{
        nodes {{
          id name number
          startsAt endsAt
          completedAt
          team {{ id name }}
          issues {{ nodes {{ id title state {{ name }} assignee {{ name }} }} }}
        }}
      }}
    }}
    """
    try:
        data = _query(query)
        return data.get("cycles", {}).get("nodes", [])
    except Exception as e:
        logger.error("get_cycles failed: %s", e)
        return []
