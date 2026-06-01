"""Run the SudoBrain local-model eval suite.

Usage:
    python -m backend.ai.eval.run_eval                      # run all tasks, all candidate models
    python -m backend.ai.eval.run_eval --task classify      # one task
    python -m backend.ai.eval.run_eval --models phi4,qwen3:14b
    python -m backend.ai.eval.run_eval --json results.json  # also dump raw results

Reads fixtures from backend/ai/eval/fixtures/.
Does NOT modify any existing code — uses ollama_engine.ask / ask_json directly.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

from backend.ai.ollama_engine import ask, list_models


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _clean(text: str) -> str:
    """Strip <think> blocks, markdown fences, leading/trailing whitespace."""
    if not text:
        return ""
    out = _THINK_RE.sub("", text)
    out = _FENCE_RE.sub("", out)
    return out.strip()


def _parse_json_lenient(text: str):
    """Try hard to extract a JSON object or array from a model response."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    # Try direct parse first
    for candidate in (cleaned,):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # Find the largest {...} or [...] span
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        first = cleaned.find(open_ch)
        last = cleaned.rfind(close_ch)
        if first >= 0 and last > first:
            snippet = cleaned[first:last + 1]
            try:
                return json.loads(snippet)
            except Exception:
                continue
    return None

FIXTURES = Path(__file__).parent / "fixtures"

# Candidate models per task — restricted to what the user actually has installed.
# The runner intersects this with `ollama list` output, so missing models are skipped.
CANDIDATES: dict[str, list[str]] = {
    "classify": ["phi4:latest", "gemma4:e4b", "qwen3:14b", "qwen2.5:14b"],
    "extract":  ["qwen3:14b", "qwen2.5:14b", "gemma4:26b", "mistral-nemo:12b", "deepseek-r1:14b"],
    "reasoning":["deepseek-r1:14b", "gpt-oss:20b", "qwen3:14b", "phi4:latest"],
}


# ---------- helpers ----------

def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _time(fn, *args, **kwargs):
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t0


def _installed_models() -> set[str]:
    return set(list_models())


def _resolve(candidates: list[str], installed: set[str]) -> list[str]:
    """Match candidate names to installed (handles :latest vs no-tag)."""
    out = []
    for c in candidates:
        if c in installed:
            out.append(c)
            continue
        base = c.split(":")[0]
        match = next((m for m in installed if m.split(":")[0] == base), None)
        if match:
            out.append(match)
    # de-dup, preserve order
    seen = set()
    return [m for m in out if not (m in seen or seen.add(m))]


# ---------- task runners ----------

def run_classify(model: str) -> dict:
    data = _load("classify")
    categories = [c.lower() for c in data["categories"]]
    cats = ", ".join(data["categories"])
    correct = 0
    latencies = []
    errors = 0

    for ex in data["examples"]:
        prompt = (
            f"Classify this text into exactly ONE of these categories: {cats}\n"
            f"Reply with only the category name, nothing else.\n\n"
            f"Text: {ex['text']}"
        )
        try:
            # Allow more tokens so reasoning models can finish their <think> block
            resp, dt = _time(ask, prompt, model=model, max_tokens=400, temperature=0.0)
            latencies.append(dt)
            cleaned = _clean(resp).lower()
            # Find first category mention anywhere in cleaned output
            pred = ""
            for cat in categories:
                if re.search(rf"\b{re.escape(cat)}\b", cleaned):
                    pred = cat
                    break
            if pred == ex["label"].lower():
                correct += 1
        except Exception:
            errors += 1

    n = len(data["examples"])
    return {
        "model": model,
        "task": "classify",
        "n": n,
        "accuracy": round(correct / n, 3) if n else 0,
        "p50_latency_s": round(statistics.median(latencies), 2) if latencies else None,
        "p95_latency_s": round(sorted(latencies)[int(len(latencies)*0.95)-1], 2) if len(latencies) >= 5 else None,
        "errors": errors,
    }


def run_extract(model: str) -> dict:
    data = _load("extract")
    field_hits = 0
    field_total = 0
    json_valid = 0
    latencies = []
    errors = 0

    for ex in data["examples"]:
        prompt = (
            "Extract a JSON object with these keys from the meeting transcript:\n"
            "  action_items: array of {owner, task, due?}\n"
            "  decisions: array of strings\n"
            "  people: array of names mentioned\n"
            "  blockers: array of strings\n\n"
            "Reply with ONLY the JSON object, no prose, no markdown.\n\n"
            f"Transcript: {ex['transcript']}"
        )
        try:
            raw, dt = _time(ask, prompt, model=model, max_tokens=2048, temperature=0.1)
            latencies.append(dt)
            resp = _parse_json_lenient(raw)
            if isinstance(resp, dict) and resp:
                json_valid += 1
                exp = ex["expected"]
                # Lightweight scoring: did each expected person appear?
                for p in exp.get("people", []):
                    field_total += 1
                    flat = json.dumps(resp).lower()
                    if p.lower() in flat:
                        field_hits += 1
                # Decisions: any expected substring present?
                for d in exp.get("decisions", []):
                    field_total += 1
                    flat = json.dumps(resp).lower()
                    key_word = d.lower().split()[0]
                    if key_word in flat:
                        field_hits += 1
                # Action items: each expected owner present?
                for ai in exp.get("action_items", []):
                    field_total += 1
                    flat = json.dumps(resp).lower()
                    if ai.get("owner", "").lower() in flat:
                        field_hits += 1
        except Exception:
            errors += 1

    return {
        "model": model,
        "task": "extract",
        "n": len(data["examples"]),
        "json_valid_rate": round(json_valid / len(data["examples"]), 3),
        "field_recall": round(field_hits / field_total, 3) if field_total else 0,
        "p50_latency_s": round(statistics.median(latencies), 2) if latencies else None,
        "errors": errors,
    }


def run_reasoning(model: str) -> dict:
    data = _load("reasoning")
    keyword_hits = 0
    keyword_total = 0
    latencies = []
    errors = 0

    for ex in data["examples"]:
        prompt = (
            "You are a helpful assistant. Answer the question concisely (2-4 sentences).\n\n"
            f"Question: {ex['question']}"
        )
        try:
            # Reasoning models need budget for <think> blocks before the answer
            resp, dt = _time(ask, prompt, model=model, max_tokens=1500, temperature=0.3)
            latencies.append(dt)
            text = _clean(resp).lower()
            for kw in ex["must_mention"]:
                keyword_total += 1
                if kw.lower() in text:
                    keyword_hits += 1
        except Exception:
            errors += 1

    return {
        "model": model,
        "task": "reasoning",
        "n": len(data["examples"]),
        "keyword_coverage": round(keyword_hits / keyword_total, 3) if keyword_total else 0,
        "p50_latency_s": round(statistics.median(latencies), 2) if latencies else None,
        "errors": errors,
    }


TASKS = {
    "classify":  run_classify,
    "extract":   run_extract,
    "reasoning": run_reasoning,
}


# ---------- output ----------

def _print_table(results: list[dict]):
    if not results:
        print("(no results)")
        return
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)

    for task, rows in by_task.items():
        print(f"\n=== {task.upper()} ===")
        # union of keys across rows, in stable order
        keys = []
        for r in rows:
            for k in r.keys():
                if k not in keys and k != "task":
                    keys.append(k)
        widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
        header = "  ".join(k.ljust(widths[k]) for k in keys)
        print(header)
        print("-" * len(header))
        for r in rows:
            print("  ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys))


# ---------- main ----------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", choices=list(TASKS.keys()), help="run a single task")
    p.add_argument("--models", help="comma-separated model overrides")
    p.add_argument("--json", help="dump raw results to this file")
    args = p.parse_args()

    installed = _installed_models()
    if not installed:
        print("No Ollama models found. Is Ollama running?")
        return

    print(f"Installed models: {sorted(installed)}\n")

    tasks_to_run = [args.task] if args.task else list(TASKS.keys())
    results = []

    for task in tasks_to_run:
        candidates = args.models.split(",") if args.models else CANDIDATES[task]
        models = _resolve(candidates, installed)
        if not models:
            print(f"[{task}] no candidate models installed, skipping")
            continue
        print(f"[{task}] running on: {models}")
        for m in models:
            print(f"  - {m} ...", end=" ", flush=True)
            t0 = time.perf_counter()
            r = TASKS[task](m)
            print(f"done in {time.perf_counter()-t0:.1f}s")
            results.append(r)

    _print_table(results)

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
        print(f"\nWrote raw results to {args.json}")


if __name__ == "__main__":
    main()
