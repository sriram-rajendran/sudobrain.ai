"""Provider configuration metadata.

This module does not call cloud providers. It only reports safe configuration
state so UI and docs can support opt-in provider setup without changing the
local-first default.
"""

from __future__ import annotations

import os


PROVIDERS = {
    "ollama": {
        "label": "Ollama",
        "base_url_env": "OLLAMA_BASE_URL",
        "model_env": "OLLAMA_MODEL",
        "api_key_env": None,
        "default_base_url": "http://localhost:11434",
        "local_default": True,
    },
    "openai_compatible": {
        "label": "OpenAI-compatible",
        "base_url_env": "SUDOBRAIN_OPENAI_COMPAT_BASE_URL",
        "model_env": "SUDOBRAIN_OPENAI_COMPAT_MODEL",
        "api_key_env": "SUDOBRAIN_OPENAI_COMPAT_API_KEY",
        "local_default": False,
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url_env": None,
        "model_env": "ANTHROPIC_MODEL",
        "api_key_env": "ANTHROPIC_API_KEY",
        "local_default": False,
    },
    "gemini": {
        "label": "Gemini",
        "base_url_env": None,
        "model_env": "GEMINI_MODEL",
        "api_key_env": "GEMINI_API_KEY",
        "local_default": False,
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url_env": "OPENROUTER_BASE_URL",
        "model_env": "OPENROUTER_MODEL",
        "api_key_env": "OPENROUTER_API_KEY",
        "local_default": False,
    },
    "groq": {
        "label": "Groq",
        "base_url_env": None,
        "model_env": "GROQ_MODEL",
        "api_key_env": "GROQ_API_KEY",
        "local_default": False,
    },
    "bedrock": {
        "label": "AWS Bedrock",
        "base_url_env": None,
        "model_env": "BEDROCK_MODEL",
        "api_key_env": "AWS_PROFILE",
        "local_default": False,
    },
    "lm_studio": {
        "label": "LM Studio",
        "base_url_env": "LM_STUDIO_BASE_URL",
        "model_env": "LM_STUDIO_MODEL",
        "api_key_env": None,
        "default_base_url": "http://localhost:1234/v1",
        "local_default": True,
    },
}


def configured_providers() -> dict:
    """Return safe provider configuration state."""
    active = os.getenv("SUDOBRAIN_LLM_PROVIDER", "ollama")
    providers = {}
    for key, meta in PROVIDERS.items():
        base_env = meta.get("base_url_env")
        model_env = meta.get("model_env")
        key_env = meta.get("api_key_env")
        base_url = os.getenv(base_env or "", meta.get("default_base_url", "")) if base_env or meta.get("default_base_url") else ""
        model = os.getenv(model_env or "", "") if model_env else ""
        key_configured = bool(os.getenv(key_env or "")) if key_env else meta.get("local_default", False)
        providers[key] = {
            "label": meta["label"],
            "active": key == active,
            "configured": bool(model or key_configured or base_url),
            "base_url_configured": bool(base_url),
            "model": model,
            "api_key_configured": key_configured,
            "base_url_env": base_env,
            "model_env": model_env,
            "api_key_env": key_env,
            "local_default": meta.get("local_default", False),
        }
    return {
        "active_provider": active,
        "local_first_default": active in {"ollama", "lm_studio"},
        "providers": providers,
    }
