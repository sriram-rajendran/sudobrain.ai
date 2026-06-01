"""Provider configuration and opt-in execution scaffolding."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


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
        "base_url_env": "GROQ_BASE_URL",
        "model_env": "GROQ_MODEL",
        "api_key_env": "GROQ_API_KEY",
        "default_base_url": "https://api.groq.com/openai/v1",
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


@dataclass
class ProviderResult:
    provider: str
    status: str
    text: str = ""
    error: str = ""
    metadata: dict[str, Any] | None = None


class ProviderClient:
    def __init__(self, provider: str, config: dict):
        self.provider = provider
        self.config = config

    def health(self) -> dict:
        return {
            "provider": self.provider,
            "configured": self.config.get("configured", False),
            "api_key_configured": self.config.get("api_key_configured", False),
            "model": self.config.get("model", ""),
        }

    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        return ProviderResult(self.provider, "unsupported", error="Provider execution is not implemented for this provider.")


class OpenAICompatibleClient(ProviderClient):
    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        base_url = os.getenv(self.config.get("base_url_env") or "", "").rstrip("/")
        model = os.getenv(self.config.get("model_env") or "", self.config.get("model") or "")
        api_key = os.getenv(self.config.get("api_key_env") or "", "")
        if not base_url or not model:
            return ProviderResult(self.provider, "not_configured", error="Base URL and model are required.")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ProviderResult(self.provider, "ok", text=text, metadata={"model": model})
        except Exception as exc:
            return ProviderResult(self.provider, "error", error=str(exc), metadata={"model": model})


class AnthropicClient(ProviderClient):
    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        api_key = os.getenv(self.config.get("api_key_env") or "", "")
        model = os.getenv(self.config.get("model_env") or "", self.config.get("model") or "claude-3-5-haiku-latest")
        if not api_key or not model:
            return ProviderResult(self.provider, "not_configured", error="API key and model are required.")
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            text = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
            return ProviderResult(self.provider, "ok", text=text, metadata={"model": model})
        except Exception as exc:
            return ProviderResult(self.provider, "error", error=str(exc), metadata={"model": model})


class GeminiClient(ProviderClient):
    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        api_key = os.getenv(self.config.get("api_key_env") or "", "")
        model = os.getenv(self.config.get("model_env") or "", self.config.get("model") or "gemini-1.5-flash")
        if not api_key or not model:
            return ProviderResult(self.provider, "not_configured", error="API key and model are required.")
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
            return ProviderResult(self.provider, "ok", text=text, metadata={"model": model})
        except Exception as exc:
            return ProviderResult(self.provider, "error", error=str(exc), metadata={"model": model})


class GroqClient(OpenAICompatibleClient):
    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        if not os.getenv("GROQ_API_KEY", ""):
            return ProviderResult(self.provider, "not_configured", error="GROQ_API_KEY is required.")
        os.environ.setdefault("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self.config["base_url_env"] = "GROQ_BASE_URL"
        return super().complete(prompt, max_tokens=max_tokens, temperature=temperature)


class BedrockClient(ProviderClient):
    def complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> ProviderResult:
        model = os.getenv(self.config.get("model_env") or "", self.config.get("model") or "")
        if not model:
            return ProviderResult(self.provider, "not_configured", error="BEDROCK_MODEL is required.")
        try:
            import boto3
        except Exception as exc:
            return ProviderResult(self.provider, "missing_dependency", error=f"boto3 is required for Bedrock: {exc}")
        try:
            client = boto3.client("bedrock-runtime")
            body = {
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            }
            response = client.converse(modelId=model, **body)
            text = "".join(
                item.get("text", "")
                for item in response.get("output", {}).get("message", {}).get("content", [])
            )
            return ProviderResult(self.provider, "ok", text=text, metadata={"model": model})
        except Exception as exc:
            return ProviderResult(self.provider, "error", error=str(exc), metadata={"model": model})


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


def get_provider_client(provider: str | None = None) -> ProviderClient:
    config = configured_providers()
    selected = provider or config["active_provider"]
    provider_config = config["providers"].get(selected, {})
    if selected in {"openai_compatible", "openrouter", "lm_studio"}:
        return OpenAICompatibleClient(selected, provider_config)
    if selected == "anthropic":
        return AnthropicClient(selected, provider_config)
    if selected == "gemini":
        return GeminiClient(selected, provider_config)
    if selected == "groq":
        return GroqClient(selected, provider_config)
    if selected == "bedrock":
        return BedrockClient(selected, provider_config)
    return ProviderClient(selected, provider_config)


def provider_health() -> dict:
    config = configured_providers()
    return {
        "active_provider": config["active_provider"],
        "providers": {
            name: get_provider_client(name).health()
            for name in config["providers"]
        },
    }


def complete_with_provider(prompt: str, provider: str | None = None, max_tokens: int = 512) -> dict:
    client = get_provider_client(provider)
    result = client.complete(prompt, max_tokens=max_tokens)
    return {
        "provider": result.provider,
        "status": result.status,
        "text": result.text,
        "error": result.error,
        "metadata": result.metadata or {},
    }
