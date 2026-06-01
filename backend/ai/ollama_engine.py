"""Local LLM engine via Ollama — fast, free, offline inference.

Used for quick tasks: classification, summarization, entity extraction, sentiment.
Falls back to local reasoning CLI for complex multi-step reasoning.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("sudobrain.ollama")

# Model from env, fallback to first available
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "")


def _get_client():
    """Lazy import to avoid startup failure if ollama isn't installed."""
    try:
        import ollama
        return ollama
    except ImportError:
        logger.warning("ollama package not installed. Run: pip install ollama")
        return None


def is_available() -> bool:
    """Check if Ollama is running and has models."""
    return len(list_models()) > 0


def list_models() -> list[str]:
    """List available Ollama models."""
    client = _get_client()
    if not client:
        return []
    try:
        response = client.list()
        # Handle both dict and object response formats
        models = getattr(response, "models", None) or response.get("models", [])
        result = []
        for m in models:
            # Model objects use .model attribute, dicts use "name" or "model"
            name = getattr(m, "model", None) or m.get("name") or m.get("model")
            if name:
                result.append(name)
        return result
    except Exception as e:
        logger.debug("list_models failed: %s", e)
        return []


def _resolve_model(model: str = None) -> str:
    """Resolve model name — use explicit, then env, then first available."""
    if model:
        return model
    # Re-read env each call (supports dynamic config)
    env_model = os.getenv("OLLAMA_MODEL", "") or DEFAULT_MODEL
    if env_model:
        return env_model
    models = list_models()
    return models[0] if models else "llama3.2"


def ask(prompt: str, model: str = None, max_tokens: int = 2048, temperature: float = 0.3) -> str:
    """Send a prompt to the local LLM and get a text response."""
    client = _get_client()
    if not client:
        return ""

    model = _resolve_model(model)

    try:
        response = client.generate(
            model=model,
            prompt=prompt,
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        )
        return response.get("response", "").strip()
    except Exception as e:
        logger.error("Ollama generate failed: %s", e)
        return ""


def ask_json(prompt: str, model: str = None, max_tokens: int = 2048) -> dict:
    """Send a prompt and parse the response as JSON."""
    response = ask(prompt, model=model, max_tokens=max_tokens, temperature=0.1)
    if not response:
        return {}

    try:
        cleaned = response.strip()

        # Strip qwen3 <think>...</think> tags if present
        if "<think>" in cleaned and "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1].strip()

        # Strip markdown code fences
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            # Handle ```json prefix
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

        # Find first { and last } to extract JSON if surrounded by prose
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            cleaned = cleaned[first_brace:last_brace + 1]

        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("Failed to parse Ollama JSON response (%s): %s", e, response[:200])
        return {}


def classify(text: str, categories: list[str], model: str = None) -> str:
    """Classify text into one of the given categories. Fast, local."""
    cats = ", ".join(categories)
    prompt = f"""Classify this text into exactly one category.
Categories: {cats}

Text: {text}

Reply with ONLY the category name, nothing else."""

    result = ask(prompt, model=model, max_tokens=50, temperature=0.1)
    # Find best match from categories
    result_lower = result.lower().strip()
    for cat in categories:
        if cat.lower() in result_lower:
            return cat
    return categories[0]


def summarize(text: str, max_words: int = 50, model: str = None) -> str:
    """Summarize text in max_words. Fast, local."""
    prompt = f"""Summarize this in {max_words} words or fewer. Be concise and direct.

{text[:3000]}"""

    return ask(prompt, model=model, max_tokens=200, temperature=0.3)


def extract_entities(text: str, model: str = None) -> dict:
    """Extract people, organizations, projects, topics from text. Local."""
    prompt = f"""Extract entities from this text. Return valid JSON only:

{{
  "people": ["name1", "name2"],
  "organizations": ["org1"],
  "projects": ["project1"],
  "topics": ["topic1", "topic2"],
  "locations": ["location1"]
}}

Text: {text[:3000]}

Return ONLY valid JSON, no other text."""

    return ask_json(prompt, model=model, max_tokens=1024)


def analyze_sentiment(text: str, model: str = None) -> dict:
    """Analyze sentiment of text. Returns score and label. Local."""
    prompt = f"""Analyze the sentiment of this text. Return valid JSON only:

{{
  "score": 0.0,
  "label": "positive",
  "reasoning": "brief explanation"
}}

Score: -1.0 (very negative) to 1.0 (very positive). 0.0 is neutral.
Label: one of "positive", "negative", "neutral", "mixed".

Text: {text[:2000]}

Return ONLY valid JSON, no other text."""

    result = ask_json(prompt, model=model, max_tokens=1024)
    if not result:
        return {"score": 0.0, "label": "neutral", "reasoning": "analysis unavailable"}
    return result


def generate_sub_queries(question: str, model: str = None) -> list[str]:
    """Decompose a question into 3-5 sub-queries for richer search. Local."""
    prompt = f"""Break this question into 3-5 specific search queries that would help answer it.
Each query should target a different angle or dimension.

Question: {question}

Return valid JSON only:
{{"queries": ["query1", "query2", "query3"]}}

Return ONLY valid JSON, no other text."""

    result = ask_json(prompt, model=model, max_tokens=512)
    return result.get("queries", [question])


def extract_relationships(text: str, model: str = None) -> list[dict]:
    """Extract entity relationships from text for knowledge graph. Local."""
    prompt = f"""Extract relationships between entities in this text. Return valid JSON only:

{{
  "relationships": [
    {{
      "source": "entity name",
      "source_type": "Person|Project|Organization|Topic",
      "target": "entity name",
      "target_type": "Person|Project|Organization|Topic",
      "relationship": "works_on|promised|decided|discussed|assigned|reports_to|belongs_to",
      "context": "brief context"
    }}
  ]
}}

Text: {text[:3000]}

Return ONLY valid JSON, no other text."""

    result = ask_json(prompt, model=model, max_tokens=2048)
    return result.get("relationships", [])
