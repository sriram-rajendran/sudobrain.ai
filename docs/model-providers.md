# Model Providers

SudoBrain is local-first by default. Cloud providers are opt-in and should be
configured only when the user explicitly wants them.

## Local Defaults

- `SUDOBRAIN_LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=gemma4:e4b`

LM Studio can also be used as a local OpenAI-compatible runtime:

```bash
SUDOBRAIN_LLM_PROVIDER=lm_studio
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=
```

## OpenAI-Compatible Endpoint

```bash
SUDOBRAIN_LLM_PROVIDER=openai_compatible
SUDOBRAIN_OPENAI_COMPAT_BASE_URL=
SUDOBRAIN_OPENAI_COMPAT_MODEL=
SUDOBRAIN_OPENAI_COMPAT_API_KEY=
```

## Cloud Provider Placeholders

The app reports safe configuration status for:

- Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL`
- OpenRouter: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`
- Groq: `GROQ_API_KEY`, `GROQ_MODEL`
- AWS Bedrock: `AWS_PROFILE`, `BEDROCK_MODEL`

The status endpoint masks secret values and reports only whether each provider is
configured:

```bash
curl http://127.0.0.1:8420/models/status
```

Provider execution remains intentionally conservative; local/Ollama routing is
the default path until provider-specific clients are implemented and reviewed.
