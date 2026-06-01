"""Local project inventory and contribution context.

This is the local source of truth that lets SudoBrain map Slack/Gmail/meeting
mentions back to actual application repositories,
contributors, tech stack, and related channels.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.projects.context")

PROJECTS_ROOT_ENV = os.getenv("SUDOBRAIN_PROJECTS_ROOT", "").strip()
PROJECTS_ROOT = Path(PROJECTS_ROOT_ENV).expanduser() if PROJECTS_ROOT_ENV else None

IGNORE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
}

GENERIC_ALIAS_TERMS = {
    "admin",
    "agent",
    "agents",
    "app",
    "backend",
    "data",
    "docs",
    "frontend",
    "include",
    "includes",
    "mobile",
    "platform",
    "script",
    "scripts",
    "test",
    "tests",
    "tool",
    "updates",
    "web",
    "website",
}

def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "unknown"


PROJECT_ALIASES = json.loads(os.getenv("SUDOBRAIN_PROJECT_ALIASES_JSON", "{}") or "{}")
RESERVED_ALIAS_OWNERS = json.loads(os.getenv("SUDOBRAIN_RESERVED_ALIAS_OWNERS_JSON", "{}") or "{}")
PROJECT_HINTS = set(PROJECT_ALIASES.keys()) | {
    _slug(alias)
    for aliases in PROJECT_ALIASES.values()
    for alias in aliases
    if isinstance(alias, str)
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _alias_allowed(repo_slug: str, alias: str) -> bool:
    norm = _norm(alias)
    if not norm:
        return False
    for reserved, owner in RESERVED_ALIAS_OWNERS.items():
        if reserved in norm and owner != repo_slug:
            return False
    return True


def _run_git(repo: Path, args: list[str], timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception as e:
        logger.debug("git command failed for %s: %s", repo, e)
        return ""


def init_project_context_tables():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_path TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS source_root TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS primary_language TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS tech_stack TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS readme_summary TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS aliases_json TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS slack_channels_json TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_commit_sha TEXT;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_commit_at TIMESTAMPTZ;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
            CREATE INDEX IF NOT EXISTS idx_projects_slug ON projects(slug);
            CREATE INDEX IF NOT EXISTS idx_projects_repo_path ON projects(repo_path);

            CREATE TABLE IF NOT EXISTS project_contributors (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT,
                email TEXT,
                commit_count INTEGER DEFAULT 0,
                last_commit_at TIMESTAMPTZ,
                recent_subjects TEXT,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, email)
            );

            CREATE TABLE IF NOT EXISTS project_sources (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_name TEXT,
                confidence REAL DEFAULT 0,
                reason TEXT,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, source, source_id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _find_repositories(root: Path | None = PROJECTS_ROOT, max_depth: int = 2) -> list[Path]:
    if root is None or not root.exists():
        return []
    repos = []
    root_depth = len(root.parts)
    for path in root.rglob(".git"):
        if not path.is_dir():
            continue
        depth = len(path.parent.parts) - root_depth
        if depth <= max_depth:
            repos.append(path.parent)
    return sorted(set(repos), key=lambda p: p.name.lower())


def _read_text(path: Path, limit: int = 6000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def _readme_summary(repo: Path) -> str:
    for name in ["README.md", "readme.md", "AGENTS.md", "CLAUDE.md"]:
        path = repo / name
        if path.exists():
            text = _read_text(path, 5000)
            lines = []
            for line in text.splitlines():
                clean = line.strip()
                if not clean:
                    continue
                if clean.startswith(("#", "-", "*")):
                    clean = clean.lstrip("#-* ").strip()
                lines.append(clean)
                if len(" ".join(lines)) > 900:
                    break
            return " ".join(lines)[:1200]
    return ""


def _detect_stack(repo: Path) -> tuple[str, list[str]]:
    stack = []
    language_counts = Counter()
    markers = {
        "package.json": "Node/TypeScript",
        "pyproject.toml": "Python",
        "requirements.txt": "Python",
        "Package.swift": "Swift",
        "go.mod": "Go",
        "Cargo.toml": "Rust",
        "pom.xml": "Java",
        "docker-compose.yml": "Docker",
        "Dockerfile": "Docker",
    }
    for filename, label in markers.items():
        if (repo / filename).exists():
            stack.append(label)

    suffix_lang = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".swift": "Swift",
        ".go": "Go",
        ".java": "Java",
        ".sql": "SQL",
    }
    for path in repo.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in suffix_lang:
            language_counts[suffix_lang[path.suffix]] += 1

    if language_counts:
        primary = language_counts.most_common(1)[0][0]
        stack.extend(k for k, _ in language_counts.most_common(4))
    else:
        primary = stack[0] if stack else ""

    return primary, sorted(set(stack))


def _package_aliases(repo: Path) -> list[str]:
    repo_slug = _slug(repo.name)
    aliases = {repo.name, repo.name.replace("-", " "), repo.name.replace("_", " ")}
    aliases.update(PROJECT_ALIASES.get(repo_slug, []))

    def add_alias(alias: str):
        if _alias_allowed(repo_slug, alias):
            aliases.add(alias)

    package_json = repo / "package.json"
    if package_json.exists():
        try:
            data = json.loads(_read_text(package_json, 20000))
            if data.get("name"):
                add_alias(str(data["name"]))
                add_alias(str(data["name"]).split("/")[-1])
        except Exception:
            pass
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        text = _read_text(pyproject, 10000)
        for match in re.findall(r"(?m)^name\s*=\s*[\"']([^\"']+)[\"']", text):
                add_alias(match)
    for child in repo.iterdir():
        if not child.is_dir() or child.name in IGNORE_DIRS or child.name.startswith("."):
            continue
        child_norm = child.name.lower()
        if len(child.name) >= 4 and any(hint in child_norm for hint in PROJECT_HINTS):
            add_alias(child.name)
            add_alias(child.name.replace("-", " "))
        child_package = child / "package.json"
        if child_package.exists():
            try:
                data = json.loads(_read_text(child_package, 20000))
                if data.get("name"):
                    add_alias(str(data["name"]))
                    add_alias(str(data["name"]).split("/")[-1])
            except Exception:
                pass
    return sorted(a for a in aliases if a)


def _recent_contributors(repo: Path) -> list[dict]:
    output = _run_git(
        repo,
        ["log", "--since=365 days ago", "--format=%aN%x1f%aE%x1f%aI%x1f%s", "--max-count=500"],
        timeout=15,
    )
    people: dict[str, dict] = {}
    for line in output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        name, email, date_str, subject = parts
        key = (email or name).lower()
        if not key:
            continue
        info = people.setdefault(
            key,
            {"name": name, "email": email.lower(), "commit_count": 0, "last_commit_at": date_str, "subjects": []},
        )
        info["commit_count"] += 1
        if date_str > (info.get("last_commit_at") or ""):
            info["last_commit_at"] = date_str
        if subject and len(info["subjects"]) < 8:
            info["subjects"].append(subject)
    return sorted(people.values(), key=lambda p: (-p["commit_count"], p.get("name") or ""))[:25]


def _last_commit(repo: Path) -> tuple[str, str]:
    output = _run_git(repo, ["log", "-1", "--format=%H%x1f%aI"], timeout=8)
    parts = output.split("\x1f")
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", ""


def _match_slack_channels(project_name: str, aliases: list[str]) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, topic, purpose, sync_enabled
            FROM slack_channels
            WHERE is_archived = FALSE
              AND sync_enabled = TRUE
            """
        ).fetchall()
    finally:
        conn.close()

    terms = {_norm(project_name)}
    for alias in aliases:
        n = _norm(alias)
        if len(n) >= 3 and n not in GENERIC_ALIAS_TERMS:
            terms.add(n)
    terms = {t for t in terms if t not in GENERIC_ALIAS_TERMS}
    matches = []
    for row in rows:
        channel_name = row["name"] or ""
        haystack = _norm(" ".join([channel_name, row["topic"] or "", row["purpose"] or ""]))
        if not haystack:
            continue
        best = max((len(t) for t in terms if t and t in haystack), default=0)
        if best:
            matches.append({
                "id": row["id"],
                "name": channel_name,
                "enabled": bool(row["sync_enabled"]),
                "confidence": min(0.95, 0.45 + best / 20),
            })
    return sorted(matches, key=lambda m: (-m["confidence"], m["name"]))[:20]


def _upsert_project(record: dict) -> int:
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM projects WHERE name = ?", (record["name"],)).fetchone()
        if existing:
            project_id = existing["id"]
            conn.execute(
                """
                UPDATE projects SET
                    slug = ?, repo_path = ?, source_root = ?, description = ?,
                    primary_language = ?, tech_stack = ?, readme_summary = ?,
                    aliases_json = ?, slack_channels_json = ?,
                    last_commit_sha = ?, last_commit_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    record["slug"],
                    record["repo_path"],
                    record["source_root"],
                    record["description"],
                    record["primary_language"],
                    json.dumps(record["tech_stack"]),
                    record["readme_summary"],
                    json.dumps(record["aliases"]),
                    json.dumps(record["slack_channels"]),
                    record["last_commit_sha"],
                    record["last_commit_at"] or None,
                    datetime.now().isoformat(),
                    project_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO projects
                (name, slug, repo_path, source_root, description, primary_language,
                 tech_stack, readme_summary, aliases_json, slack_channels_json,
                 last_commit_sha, last_commit_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["name"],
                    record["slug"],
                    record["repo_path"],
                    record["source_root"],
                    record["description"],
                    record["primary_language"],
                    json.dumps(record["tech_stack"]),
                    record["readme_summary"],
                    json.dumps(record["aliases"]),
                    json.dumps(record["slack_channels"]),
                    record["last_commit_sha"],
                    record["last_commit_at"] or None,
                    datetime.now().isoformat(),
                ),
            )
            project_id = cur.lastrowid

        conn.execute("DELETE FROM project_contributors WHERE project_id = ?", (project_id,))
        for person in record["contributors"]:
            conn.execute(
                """
                INSERT INTO project_contributors
                (project_id, name, email, commit_count, last_commit_at, recent_subjects, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (project_id, email) DO UPDATE SET
                    name = EXCLUDED.name,
                    commit_count = EXCLUDED.commit_count,
                    last_commit_at = EXCLUDED.last_commit_at,
                    recent_subjects = EXCLUDED.recent_subjects,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    project_id,
                    person.get("name"),
                    person.get("email") or f"unknown-{_slug(person.get('name',''))}@local",
                    person.get("commit_count", 0),
                    person.get("last_commit_at") or None,
                    json.dumps(person.get("subjects", [])),
                    datetime.now().isoformat(),
                ),
            )

        conn.execute("DELETE FROM project_sources WHERE project_id = ? AND source = 'slack'", (project_id,))
        for channel in record["slack_channels"]:
            conn.execute(
                """
                INSERT INTO project_sources
                (project_id, source, source_id, source_name, confidence, reason, updated_at)
                VALUES (?, 'slack', ?, ?, ?, ?, ?)
                ON CONFLICT (project_id, source, source_id) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    confidence = EXCLUDED.confidence,
                    reason = EXCLUDED.reason,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    project_id,
                    channel["id"],
                    channel["name"],
                    channel["confidence"],
                    "channel name/topic matched project alias",
                    datetime.now().isoformat(),
                ),
            )
        conn.commit()
        return project_id
    finally:
        conn.close()


def _upsert_graph(record: dict):
    try:
        from backend.graph.neo4j_client import get_driver, upsert_person

        driver = get_driver()
        if not driver:
            return
        with driver.session() as session:
            session.run(
                """
                MERGE (p:Project {name: $name})
                SET p.slug=$slug, p.repo_path=$repo_path, p.description=$description,
                    p.primary_language=$primary_language, p.tech_stack=$tech_stack,
                    p.updated_at=datetime()
                """,
                name=record["name"],
                slug=record["slug"],
                repo_path=record["repo_path"],
                description=record["description"],
                primary_language=record["primary_language"],
                tech_stack=", ".join(record["tech_stack"]),
            )
            for contributor in record["contributors"]:
                email = contributor.get("email") or ""
                name = contributor.get("name") or email
                if not name:
                    continue
                upsert_person(name, email=email or None)
                session.run(
                    """
                    MATCH (person:Person)
                    WHERE toLower(person.name) = toLower($name)
                       OR ($email IS NOT NULL AND person.email IS NOT NULL AND toLower(person.email) = toLower($email))
                    WITH person
                    ORDER BY CASE
                        WHEN $email IS NOT NULL AND person.email IS NOT NULL AND toLower(person.email) = toLower($email) THEN 0
                        ELSE 1
                    END
                    LIMIT 1
                    MATCH (project:Project {name: $project})
                    MERGE (person)-[r:CONTRIBUTED_TO]->(project)
                    SET r.commit_count=$commit_count, r.last_commit_at=$last_commit_at
                    """,
                    email=email or None,
                    name=name,
                    project=record["name"],
                    commit_count=contributor.get("commit_count", 0),
                    last_commit_at=contributor.get("last_commit_at"),
                )
    except Exception as e:
        logger.warning("project graph upsert skipped for %s: %s", record["name"], e)


def build_project_record(repo: Path, source_root: Path = PROJECTS_ROOT) -> dict:
    aliases = _package_aliases(repo)
    primary_language, tech_stack = _detect_stack(repo)
    last_sha, last_at = _last_commit(repo)
    summary = _readme_summary(repo)
    return {
        "name": repo.name,
        "slug": _slug(repo.name),
        "repo_path": str(repo),
        "source_root": str(source_root),
        "description": summary[:500],
        "readme_summary": summary,
        "primary_language": primary_language,
        "tech_stack": tech_stack,
        "aliases": aliases,
        "contributors": _recent_contributors(repo),
        "last_commit_sha": last_sha,
        "last_commit_at": last_at,
        "slack_channels": _match_slack_channels(repo.name, aliases),
    }


def sync_project_context(root: Path | None = PROJECTS_ROOT) -> dict:
    """Scan local repositories and persist app/contributor/channel context."""
    init_project_context_tables()
    if root is None:
        return {
            "root": "",
            "repositories_found": 0,
            "projects_synced": 0,
            "skipped": "SUDOBRAIN_PROJECTS_ROOT not configured",
            "projects": [],
        }
    repos = _find_repositories(root)
    records = []
    for repo in repos:
        try:
            record = build_project_record(repo, source_root=root)
            record["project_id"] = _upsert_project(record)
            _upsert_graph(record)
            records.append(record)
        except Exception as e:
            logger.warning("project scan failed for %s: %s", repo, e)

    return {
        "root": str(root),
        "repositories_found": len(repos),
        "projects_synced": len(records),
        "projects": [
            {
                "name": r["name"],
                "primary_language": r["primary_language"],
                "contributors": len(r["contributors"]),
                "slack_channels": [c["name"] for c in r["slack_channels"][:5]],
                "last_commit_at": r["last_commit_at"],
            }
            for r in records
        ],
    }


def list_project_context() -> list[dict]:
    init_project_context_tables()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, slug, repo_path, primary_language, tech_stack,
                   readme_summary, slack_channels_json, last_commit_at, updated_at
            FROM projects
            WHERE repo_path IS NOT NULL AND repo_path != ''
            ORDER BY name
            """
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["tech_stack"] = json.loads(item.get("tech_stack") or "[]")
            except Exception:
                item["tech_stack"] = []
            try:
                item["slack_channels"] = json.loads(item.get("slack_channels_json") or "[]")
            except Exception:
                item["slack_channels"] = []
            item.pop("slack_channels_json", None)
            out.append(item)
        return out
    finally:
        conn.close()
