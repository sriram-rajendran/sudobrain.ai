"""Local reasoning CLI engine for SudoBrain.

The backend can call a user-configured local CLI in non-interactive mode with a
local provider. If no CLI is configured, callers fall back to deterministic
local search paths.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

WORKSPACE_DIR = Path(
    os.getenv(
        "SUDOBRAIN_DATA_DIR",
        str(Path.home() / ".sudobrain"),
    )
) / "workspace"

PROJECT_DIR = Path(
    os.getenv("SUDOBRAIN_PROJECT_DIR", str(Path(__file__).resolve().parent.parent.parent))
)

LOCAL_LLM_MODEL = (
    os.getenv("SUDOBRAIN_LLM_MODEL")
    or os.getenv("SUDOBRAIN_LEGACY_LLM_MODEL")
    or os.getenv("OLLAMA_MODEL")
    or "gemma4:e4b"
)
LOCAL_LLM_PROVIDER = os.getenv("SUDOBRAIN_LLM_PROVIDER") or os.getenv("SUDOBRAIN_LEGACY_LLM_PROVIDER", "ollama")
LOCAL_LLM_COMMAND = os.getenv("SUDOBRAIN_LLM_COMMAND", "").strip()


def load_identity() -> str:
    """Load local identity files as context."""
    parts = []
    for filename in ["SOUL.md", "USER.md", "RULES.md"]:
        filepath = WORKSPACE_DIR / filename
        if filepath.exists():
            parts.append(f"--- {filename} ---\n{filepath.read_text().strip()}")
    return "\n\n".join(parts)


def _run_local_llm(prompt: str, max_wait: int) -> str:
    if not LOCAL_LLM_COMMAND:
        return "Local reasoning CLI is not configured. Set SUDOBRAIN_LLM_COMMAND to enable synthesis."

    with tempfile.NamedTemporaryFile("r", delete=False, suffix=".txt") as out:
        output_path = out.name

    cmd = [
        LOCAL_LLM_COMMAND,
        "exec",
        "--oss",
        "--local-provider",
        LOCAL_LLM_PROVIDER,
        "-m",
        LOCAL_LLM_MODEL,
        "-s",
        "read-only",
        "--ephemeral",
        "-C",
        str(PROJECT_DIR),
        "-o",
        output_path,
        "-",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=max_wait,
            cwd=str(PROJECT_DIR),
        )

        answer = Path(output_path).read_text().strip() if Path(output_path).exists() else ""
        if answer:
            return answer

        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip()
            return f"Error from local reasoning CLI: {error[:1000]}"

        return (result.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return "Local reasoning CLI timed out. Try a simpler question."
    except FileNotFoundError:
        return "Local reasoning CLI not found. Check SUDOBRAIN_LLM_COMMAND and PATH."
    except Exception as e:
        return f"Error invoking local reasoning CLI: {e}"
    finally:
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass


def ask(prompt: str, context: str = "", max_wait: int = 120) -> str:
    """Ask local reasoning engine with identity and optional context."""
    identity = load_identity()
    full_prompt = f"""{identity}

--- CONTEXT ---
{context}

--- USER REQUEST ---
{prompt}"""
    return _run_local_llm(full_prompt, max_wait=max_wait)


def ask_with_knowledge(prompt: str, knowledge_context: list[dict], max_wait: int = 120) -> dict:
    """Ask local reasoning engine with knowledge base context and return a structured response."""
    context_parts = []
    sources = []
    for i, entry in enumerate(knowledge_context):
        text = entry.get("text", "")
        source = entry.get("source", "Unknown")
        date = entry.get("date", "")
        speaker = entry.get("speaker_label", "")

        context_parts.append(f"[{i + 1}] {speaker}: {text}")
        sources.append({
            "index": i + 1,
            "source": source,
            "date": date,
            "text": text[:100],
        })

    context_text = "\n".join(context_parts) if context_parts else "No relevant data found in knowledge base."

    enhanced_prompt = f"""Based on the knowledge base entries below, answer the user's question.

Rules:
- Tag each claim with [HIGH], [MEDIUM], or [LOW] confidence.
- [HIGH] = directly stated in the data below.
- [MEDIUM] = inferred from patterns across multiple entries.
- [LOW] = estimated, not directly supported.
- Cite sources using [Source: N] where N is the entry number.
- If no data supports the answer, say "I don't have information about this in your knowledge base".

Knowledge Base Entries:
{context_text}

User Question: {prompt}"""

    answer = ask(enhanced_prompt, max_wait=max_wait)
    high_count = answer.count("[HIGH]")
    medium_count = answer.count("[MEDIUM]")
    low_count = answer.count("[LOW]")

    if high_count > medium_count + low_count:
        overall = "high"
    elif medium_count > 0:
        overall = "medium"
    elif low_count > 0:
        overall = "low"
    else:
        overall = "medium"

    return {"answer": answer, "sources": sources, "confidence": overall}


def _empty_knowledge(summary: str = "") -> dict:
    return {
        "summary": summary[:500],
        "action_items": [],
        "decisions": [],
        "promises": [],
        "topics": [],
        "project": None,
    }


def _extract_json_object(text: str) -> str:
    """Return the first balanced JSON object from a model response."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    if cleaned.startswith("{"):
        return cleaned

    start = cleaned.find("{")
    if start < 0:
        return cleaned

    depth = 0
    in_string = False
    escape = False
    for idx, char in enumerate(cleaned[start:], start=start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:idx + 1]
    return cleaned[start:]


def _parse_knowledge_response(response: str) -> dict | None:
    try:
        parsed = json.loads(_extract_json_object(response))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    for key in ["action_items", "decisions", "promises", "topics"]:
        if not isinstance(parsed.get(key), list):
            parsed[key] = []
    summary = parsed.get("summary", "")
    if not isinstance(summary, str):
        summary = json.dumps(summary, ensure_ascii=False)
    parsed["summary"] = summary
    project = parsed.get("project")
    if project is not None and not isinstance(project, str):
        parsed["project"] = str(project)
    normalized_actions = []
    for item in parsed["action_items"]:
        if not isinstance(item, dict):
            item = {"text": str(item)}
        item["text"] = str(item.get("text") or "")
        normalized_actions.append(item)
    parsed["action_items"] = normalized_actions

    normalized_decisions = []
    for item in parsed["decisions"]:
        if not isinstance(item, dict):
            item = {"text": str(item)}
        item["text"] = str(item.get("text") or "")
        normalized_decisions.append(item)
    parsed["decisions"] = normalized_decisions

    normalized_promises = []
    for item in parsed["promises"]:
        if not isinstance(item, dict):
            item = {"text": str(item)}
        item["text"] = str(item.get("text") or "")
        normalized_promises.append(item)
    parsed["promises"] = normalized_promises

    normalized_topics = []
    for item in parsed["topics"]:
        if not isinstance(item, dict):
            item = {"title": str(item), "summary": ""}
        item["title"] = str(item.get("title") or "")
        item["summary"] = str(item.get("summary") or "")
        normalized_topics.append(item)
    parsed["topics"] = normalized_topics
    parsed.setdefault("project", None)
    return parsed


def _merge_knowledge(parts: list[dict]) -> dict:
    merged = _empty_knowledge()
    summaries = []
    projects = []
    seen: set[tuple[str, str]] = set()
    for part in parts:
        if part.get("summary"):
            summaries.append(part["summary"])
        if part.get("project"):
            projects.append(part["project"])
        for key in ["action_items", "decisions", "promises", "topics"]:
            for item in part.get(key, []):
                if not isinstance(item, dict):
                    continue
                identity = (key, json.dumps(item, sort_keys=True, ensure_ascii=False).lower())
                if identity in seen:
                    continue
                seen.add(identity)
                merged[key].append(item)
    merged["summary"] = " ".join(summaries)[:1000]
    merged["project"] = projects[0] if projects else None
    return merged


def _split_transcript(text: str, max_chars: int = 6500) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _extract_knowledge_once(transcript_text: str, agents_context: str, max_wait: int) -> dict:
    prompt = f"""{agents_context}

Extract structured knowledge from this transcript. Return valid JSON with these fields:

{{
  "summary": "2-3 sentence summary",
  "action_items": [
    {{"text": "what needs to be done", "assignee": "who", "due_date": "YYYY-MM-DD or null"}}
  ],
  "decisions": [
    {{"text": "what was decided", "made_by": "who", "context": "brief context"}}
  ],
  "promises": [
    {{"text": "what was promised", "promised_by": "who", "promised_to": "whom", "due_date": "YYYY-MM-DD or null"}}
  ],
  "topics": [
    {{"title": "topic name", "summary": "brief summary"}}
  ],
  "project": "project name if identifiable, null otherwise"
}}

Return ONLY valid JSON, no markdown code blocks, no other text.

Transcript:
{transcript_text}"""

    response = ask(prompt, max_wait=max_wait)
    parsed = _parse_knowledge_response(response)
    if parsed is not None:
        return parsed

    retry_prompt = f"""Your previous response was not valid JSON.

Return ONLY one JSON object matching this schema:
{{
  "summary": "2-3 sentence summary",
  "action_items": [{{"text": "what needs to be done", "assignee": "who or null", "due_date": "YYYY-MM-DD or null"}}],
  "decisions": [{{"text": "what was decided", "made_by": "who or null", "context": "brief context"}}],
  "promises": [{{"text": "what was promised", "promised_by": "who or null", "promised_to": "who or null", "due_date": "YYYY-MM-DD or null"}}],
  "topics": [{{"title": "topic name", "summary": "brief summary"}}],
  "project": "project name if identifiable, null otherwise"
}}

No markdown. No explanation. Use the transcript below.

Transcript:
{transcript_text[:12000]}"""
    retry_response = ask(retry_prompt, max_wait=max_wait)
    parsed = _parse_knowledge_response(retry_response)
    if parsed is not None:
        return parsed

    print(f"[local reasoning CLI] Failed to parse JSON response: {response[:200]}")
    return _empty_knowledge(response)


def extract_knowledge(transcript_text: str, max_wait: int = 120) -> dict:
    """Extract structured knowledge from transcript text using local reasoning engine."""
    agents_file = WORKSPACE_DIR / "AGENTS.md"
    agents_context = agents_file.read_text() if agents_file.exists() else ""
    transcript_text = transcript_text or ""

    chunks = _split_transcript(transcript_text)
    if len(chunks) == 1:
        return _extract_knowledge_once(chunks[0], agents_context, max_wait)

    extracted = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_context = f"[Transcript chunk {idx} of {len(chunks)}]\n{chunk}"
        extracted.append(_extract_knowledge_once(chunk_context, agents_context, max_wait))
    return _merge_knowledge(extracted)
