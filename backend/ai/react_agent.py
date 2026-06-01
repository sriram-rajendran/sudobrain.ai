"""ReACT chat agent — multi-step reasoning with tool invocation.

Instead of single-shot answers, the agent:
  Think -> decide which tool to call -> observe result -> think again -> ... -> final answer

Available tools:
  - search_transcripts: FTS search across transcripts
  - semantic_search: Vector similarity search
  - lookup_person: Get person's network from graph
  - lookup_project: Get project details from graph
  - check_promises: Get pending promises
  - check_tasks: Get pending action items
"""

import json
import logging
import re
from typing import Optional

from backend.ai.local_llm_engine import ask, load_identity
from backend.storage import database as db

logger = logging.getLogger("sudobrain.react")

MAX_ITERATIONS = 5

TOOL_DESCRIPTIONS = """Available tools:
1. search_transcripts(query) — Full-text search across all meeting transcripts
2. semantic_search(query) — Find semantically similar content even with different wording
3. lookup_person(name) — Get a person's connections: promises, tasks, decisions, meetings
4. lookup_project(name) — Get everything connected to a project
5. check_promises(filter) — Get pending promises. Filter: "all", "overdue", or a person's name
6. check_tasks(filter) — Get pending action items. Filter: "all", or a project name
7. check_decisions(limit) — Get recent decisions
8. final_answer(answer) — Provide the final answer to the user. MUST be called to end."""

SYSTEM_PROMPT = """You are SudoBrain's reasoning agent. Answer the user's question by searching their knowledge base.

{tools}

Respond in this exact format each turn:

Thought: [your reasoning about what to do next]
Action: [tool_name]
Input: [tool input]

OR when you have enough information:

Thought: [your reasoning]
Action: final_answer
Input: [your complete answer to the user]

Rules:
- Call 2-4 tools before giving a final answer for complex questions
- For simple factual questions, 1 tool call may be enough
- Always end with final_answer
- Cite specific data from tool results in your answer
- If no data is found, say so honestly"""


def _execute_tool(tool_name: str, tool_input: str) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "search_transcripts":
            results = db.search_transcripts(tool_input, limit=5)
            if not results:
                return "No transcript matches found."
            return "\n".join(
                f"- [{r.get('mode', 'recording')} {r.get('recording_date', '')[:10]}] "
                f"{r.get('speaker_label', '')}: {r.get('text', '')[:200]}"
                for r in results
            )

        elif tool_name == "semantic_search":
            from backend.storage.vectors import semantic_search
            results = semantic_search(tool_input, top_k=5, min_score=0.3)
            if not results:
                return "No semantic matches found."
            return "\n".join(
                f"- [score:{r.get('score', 0):.2f}] {r.get('text', '')[:200]}"
                for r in results
            )

        elif tool_name == "lookup_person":
            try:
                from backend.graph.neo4j_client import get_person_network
                result = get_person_network(tool_input)
                connections = result.get("connections", [])
                if not connections:
                    return f"No graph data found for '{tool_input}'."
                lines = [f"Person: {tool_input}, {len(connections)} connections:"]
                for c in connections[:10]:
                    props = c.get("properties", {})
                    text = props.get("text", props.get("description", props.get("name", "")))
                    lines.append(f"  - [{c['relationship']}] {c['node_type']}: {str(text)[:100]}")
                return "\n".join(lines)
            except Exception:
                return f"Graph not available. No data for '{tool_input}'."

        elif tool_name == "lookup_project":
            try:
                from backend.graph.neo4j_client import get_project_graph
                result = get_project_graph(tool_input)
                nodes = result.get("nodes", [])
                if not nodes:
                    return f"No graph data found for project '{tool_input}'."
                lines = [f"Project: {tool_input}, {len(nodes)} connected items:"]
                for n in nodes[:10]:
                    props = n.get("properties", {})
                    text = props.get("text", props.get("description", ""))
                    lines.append(f"  - {n['type']}: {str(text)[:100]}")
                return "\n".join(lines)
            except Exception:
                return f"Graph not available. No data for project '{tool_input}'."

        elif tool_name == "check_promises":
            conn = db.get_connection()
            try:
                if tool_input and tool_input.lower() == "overdue":
                    rows = conn.execute(
                        "SELECT * FROM promises WHERE status='pending' AND due_date < date('now')"
                    ).fetchall()
                elif tool_input and tool_input.lower() != "all":
                    rows = conn.execute(
                        "SELECT * FROM promises WHERE status='pending' AND (promised_by_name LIKE ? OR promised_to_name LIKE ?)",
                        (f"%{tool_input}%", f"%{tool_input}%"),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM promises WHERE status='pending' ORDER BY created_at DESC LIMIT 10"
                    ).fetchall()
            finally:
                conn.close()
            if not rows:
                return "No pending promises found."
            return "\n".join(
                f"- {r['promised_by_name']} -> {r['promised_to_name']}: {r['description']} (due: {r['due_date'] or 'no date'})"
                for r in rows
            )

        elif tool_name == "check_tasks":
            if tool_input and tool_input.lower() != "all":
                items = db.get_pending_action_items(project=tool_input)
            else:
                items = db.get_pending_action_items()
            if not items:
                return "No pending tasks found."
            return "\n".join(
                f"- {a['text']} (assignee: {a.get('assignee', 'unassigned')}, due: {a.get('due_date', 'no date')})"
                for a in items[:10]
            )

        elif tool_name == "check_decisions":
            limit = 5
            try:
                limit = int(tool_input)
            except (ValueError, TypeError):
                pass
            conn = db.get_connection()
            try:
                rows = conn.execute(
                    "SELECT text, made_by, context, created_at FROM decisions ORDER BY created_at DESC LIMIT ?",
                    (min(limit, 20),),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                return "No decisions found."
            return "\n".join(
                f"- {r['text']} (by: {r['made_by']}, {r['created_at'][:10]})"
                for r in rows
            )

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        return f"Tool error: {e}"


def _parse_action(response: str) -> tuple[str, str]:
    """Parse Action and Input from LLM response."""
    action_match = re.search(r'Action:\s*(.+)', response)
    input_match = re.search(r'Input:\s*(.+)', response, re.DOTALL)

    if not action_match:
        return "final_answer", response

    action = action_match.group(1).strip()
    tool_input = input_match.group(1).strip() if input_match else ""

    # Clean up — sometimes the LLM includes extra lines after Input
    if "\nThought:" in tool_input:
        tool_input = tool_input.split("\nThought:")[0].strip()

    return action, tool_input


def react_chat(query: str, max_iterations: int = MAX_ITERATIONS) -> dict:
    """Run a ReACT reasoning loop to answer a user question.

    Returns dict with 'answer', 'sources', 'confidence', 'reasoning_steps'.
    """
    identity = load_identity()
    conversation = f"""{identity}

{SYSTEM_PROMPT.format(tools=TOOL_DESCRIPTIONS)}

User question: {query}
"""

    steps = []

    for i in range(max_iterations):
        response = ask(conversation, max_wait=60)

        if not response:
            break

        action, tool_input = _parse_action(response)
        logger.info("ReACT step %d: %s(%s)", i + 1, action, tool_input[:50])

        if action == "final_answer":
            steps.append({"step": i + 1, "type": "answer", "content": tool_input})
            return {
                "answer": tool_input,
                "sources": [],
                "confidence": "high" if len(steps) >= 2 else "medium",
                "reasoning_steps": steps,
            }

        # Execute tool
        result = _execute_tool(action, tool_input)
        steps.append({
            "step": i + 1,
            "type": "tool_call",
            "tool": action,
            "input": tool_input,
            "result": result[:500],
        })

        # Add to conversation for next iteration
        conversation += f"""
{response}

Observation: {result}

"""

    # If we exhausted iterations without a final_answer, use last response
    return {
        "answer": "I searched your knowledge base but couldn't form a complete answer. Try rephrasing your question.",
        "sources": [],
        "confidence": "low",
        "reasoning_steps": steps,
    }
