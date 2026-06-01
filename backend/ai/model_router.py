"""Tiered model routing — picks the right local Ollama model for each task type.

Tier 1 (Fast): phi4 / gemma4:e4b — classification, sentiment, tagging
Tier 2 (Default): qwen3:14b / qwen2.5:14b — knowledge extraction, JSON, multilingual
Tier 3 (Reasoning): deepseek-r1:14b — multi-step ReACT, complex queries
Tier 4 (Quality): gemma4:26b — highest quality extraction when time allows
Fallback: local reasoning CLI — synthesis, reports, complex reasoning
"""

import logging
import os
from typing import Literal

logger = logging.getLogger("sudobrain.model_router")

TaskType = Literal[
    "classify",       # quick classification, tagging
    "sentiment",      # sentiment analysis
    "summarize",      # short summarization
    "extract",        # knowledge extraction from transcripts/Slack
    "extract_quality",# highest-quality extraction (slower)
    "reasoning",      # multi-step ReACT, complex queries
    "json",           # structured JSON output
]

# Priority lists per task — first available model wins
TIER_MAP: dict[TaskType, list[str]] = {
    "classify":       ["phi4", "gemma4:e4b", "qwen3:14b"],
    "sentiment":      ["phi4", "gemma4:e4b", "qwen3:14b"],
    "summarize":      ["phi4", "qwen3:14b", "qwen2.5:14b"],
    "extract":        ["qwen3:14b", "qwen2.5:14b", "gemma4:26b"],
    "extract_quality":["gemma4:26b", "qwen3:14b", "qwen2.5:14b"],
    "reasoning":      ["deepseek-r1:14b", "qwen3:14b"],
    "json":           ["qwen2.5:14b", "qwen3:14b", "gemma4:26b"],
}

_available_models: set[str] | None = None


def _get_available_models() -> set[str]:
    """Get available Ollama models (cached after first call)."""
    global _available_models
    if _available_models is not None:
        return _available_models

    try:
        from backend.ai.ollama_engine import list_models
        models = list_models()
        _available_models = set(models)
        logger.info("Available Ollama models: %s", sorted(_available_models))
    except Exception as e:
        logger.warning("Could not list Ollama models: %s", e)
        _available_models = set()

    return _available_models


def invalidate_cache():
    """Force re-detection of available models (call after pulling new models)."""
    global _available_models
    _available_models = None


def get_model(task: TaskType) -> str | None:
    """Return the best available model for a given task type.

    Returns None if no suitable model found (caller should fall back to local reasoning CLI).
    """
    available = _get_available_models()
    if not available:
        return None

    candidates = TIER_MAP.get(task, TIER_MAP["extract"])
    for candidate in candidates:
        # Check if any available model name starts with or matches the candidate
        for model in available:
            model_base = model.split(":")[0]  # strip tag
            cand_base = candidate.split(":")[0]
            if model_base == cand_base or model == candidate:
                logger.debug("Task '%s' → model '%s'", task, model)
                return model

    logger.debug("No model found for task '%s', will use local reasoning CLI", task)
    return None


def ask(prompt: str, task: TaskType = "extract", max_tokens: int = 2048,
        temperature: float = 0.3) -> str:
    """Route a prompt to the best available model for the task."""
    from backend.ai.ollama_engine import ask as ollama_ask
    model = get_model(task)
    if not model:
        logger.debug("No Ollama model for task '%s', skipping (use local reasoning CLI)", task)
        return ""
    return ollama_ask(prompt, model=model, max_tokens=max_tokens, temperature=temperature)


def ask_json(prompt: str, task: TaskType = "json", max_tokens: int = 2048) -> dict:
    """Route a JSON prompt to the best available model."""
    from backend.ai.ollama_engine import ask_json as ollama_ask_json
    model = get_model(task)
    if not model:
        return {}
    return ollama_ask_json(prompt, model=model, max_tokens=max_tokens)


def classify(text: str, categories: list[str]) -> str:
    """Fast local classification."""
    from backend.ai.ollama_engine import classify as ollama_classify
    model = get_model("classify")
    if not model:
        return categories[0]
    return ollama_classify(text, categories, model=model)


def analyze_sentiment(text: str) -> dict:
    """Fast local sentiment analysis."""
    from backend.ai.ollama_engine import analyze_sentiment as ollama_sentiment
    model = get_model("sentiment")
    if not model:
        return {"score": 0.0, "label": "neutral", "reasoning": "no model available"}
    return ollama_sentiment(text, model=model)


def summarize(text: str, max_words: int = 50) -> str:
    """Fast local summarization."""
    from backend.ai.ollama_engine import summarize as ollama_summarize
    model = get_model("summarize")
    if not model:
        return ""
    return ollama_summarize(text, max_words=max_words, model=model)


def generate_sub_queries(question: str) -> list[str]:
    """Decompose a question into sub-queries using reasoning model."""
    from backend.ai.ollama_engine import generate_sub_queries as ollama_queries
    model = get_model("reasoning")
    if not model:
        return [question]
    return ollama_queries(question, model=model)
