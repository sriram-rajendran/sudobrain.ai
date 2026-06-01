# Setup

This guide starts SudoBrain without private source credentials. Add integrations
only after the local backend is healthy.

## 1. Environment

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
```

Or use the helper:

```bash
./scripts/bootstrap_local.sh
```

The example environment disables external sync by default.

`SUDOBRAIN_API_TOKEN` is optional for single-user local development. If you set
it and also want localhost clients to authenticate, set
`SUDOBRAIN_TRUST_LOCALHOST=false`.

For read-only local browsing, set `SUDOBRAIN_LOCAL_ROLE=viewer`; mutating API
calls will return `403`. Set `SUDOBRAIN_RATE_LIMIT_PER_MINUTE=0` only for
trusted local development where request throttling is not needed.

## 2. Local Services

Start Postgres and Neo4j:

```bash
docker compose up -d postgres neo4j
```

## 3. Backend

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8420 --reload
```

Verify:

```bash
curl http://127.0.0.1:8420/health
curl http://127.0.0.1:8420/graph/status
curl http://127.0.0.1:8420/sync/audit
```

Run a no-credential smoke test:

```bash
make smoke
```

## 4. Demo Workspace

Load public-safe synthetic data:

```bash
make demo
```

This creates demo meetings, transcripts, people, projects, tasks, decisions,
promises, Slack-style messages, and Gmail-style messages. It replaces previous
demo rows by default and does not touch non-demo records.

Useful checks:

```bash
curl 'http://127.0.0.1:8420/search?q=Atlas'
curl 'http://127.0.0.1:8420/onboarding/status'
curl 'http://127.0.0.1:8420/knowledge/export?format=markdown'
```

## 5. No-Integration Mode

Leave these disabled to run without private credentials:

```bash
SUDOBRAIN_SYNC_GMAIL=false
SUDOBRAIN_SYNC_SLACK=false
SUDOBRAIN_SYNC_FATHOM=false
SUDOBRAIN_SYNC_PROJECT_CONTEXT=false
```

This mode is useful for local development, UI work, and database/schema checks.

Local synthesis is optional. Set `SUDOBRAIN_LLM_COMMAND` only when you have a
local non-interactive reasoning CLI installed; otherwise SudoBrain uses local
search fallbacks for chat responses.

## 6. Optional Integrations

Enable only the sources you want:

```bash
SUDOBRAIN_SYNC_SLACK=true
SLACK_USER_TOKEN=

SUDOBRAIN_SYNC_GMAIL=true
GMAIL_CREDENTIALS_FILE=./credentials.json
GMAIL_TOKEN_FILE=./token.json

SUDOBRAIN_SYNC_FATHOM=true
FATHOM_API_TOKEN=

SUDOBRAIN_SYNC_PROJECT_CONTEXT=true
SUDOBRAIN_PROJECTS_ROOT=/path/to/your/repos
```

Use read-only scopes whenever the provider supports them.

## 7. Optional Encrypted Secrets

SudoBrain can keep opt-in integration/provider secrets in an encrypted local
file instead of plain environment values.

```bash
curl -X POST http://127.0.0.1:8420/security/secrets/key
```

Store the returned key privately as `SUDOBRAIN_SECRETS_KEY`, then use:

```bash
curl http://127.0.0.1:8420/security/secrets/status
curl -X POST http://127.0.0.1:8420/security/secrets \
  -H 'Content-Type: application/json' \
  -d '{"name":"OPENROUTER_API_KEY","value":"replace-me"}'
```

## 8. Configurable Aliases

Project and person normalization is intentionally configurable. Example:

```bash
SUDOBRAIN_PROJECT_ALIASES_JSON='{"project-a":["project a","legacy project name"]}'
SUDOBRAIN_RESERVED_ALIAS_OWNERS_JSON='{"projecta":"project-a"}'
SUDOBRAIN_PROJECT_PATTERNS_JSON='{"Project A":["\\bproject a\\b","\\blegacy project name\\b"]}'
SUDOBRAIN_PERSON_ALIASES_JSON='{"alex":"Alex Rivera"}'
SUDOBRAIN_EMAIL_NAME_OVERRIDES_JSON='{"alex@example.com":"Alex Rivera"}'
SUDOBRAIN_SLACK_ID_OVERRIDES_JSON='{"U00000000":"Alex Rivera"}'
SUDOBRAIN_ACCEPTED_EXTERNAL_PROJECTS='Operations,Sales'
SUDOBRAIN_REQUIRED_PROJECTS='Project A'
SUDOBRAIN_STRICT_PROJECT_AUDIT=true
SUDOBRAIN_COMMIT_RISK_KEYWORDS_JSON='{"security review":0.15,"launch":0.1}'
SUDOBRAIN_PROJECT_KEYWORDS='project a,operations'
SUDOBRAIN_INTERNAL_EMAIL_DOMAINS='example.com'
SELF_EMAIL='alex@example.com'
```

Keep real aliases in `.env` or another private config channel, not in public
source files.

## 9. Full Docker Compose

Run the backend with Postgres and Neo4j in containers:

```bash
make docker-full-up
```

The macOS app still runs locally and talks to `http://127.0.0.1:8420`.

## 10. macOS App

```bash
cd app
swift build
```

Run the backend before using app features that call local APIs.
