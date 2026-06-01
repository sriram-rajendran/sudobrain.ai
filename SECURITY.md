# Security Policy

## Supported Versions

This project is early-stage. Security fixes should target the default branch
unless a maintained release branch is documented.

## Reporting a Vulnerability

Please open a private security advisory or contact the maintainers directly.
Do not include secrets, source messages, recordings, or private transcripts in a
public issue.

## Security Expectations

- Keep `.env`, OAuth tokens, credentials, recordings, transcripts, database
  files, and generated local data out of Git.
- Use least-privilege, read-only scopes for Slack, Gmail, Fathom, and similar
  integrations where possible.
- Use `SUDOBRAIN_LOCAL_ROLE=viewer` for read-only local sessions and `editor`
  for non-admin write sessions.
- Store optional provider/integration secrets in the encrypted local store when
  `SUDOBRAIN_SECRETS_KEY` is configured.
- Review extracted actions, decisions, and promises before using them for
  operational decisions.
- Rotate credentials immediately if they were committed or shared.

## Local Secret Store

Generate a key without storing it:

```bash
curl -X POST http://127.0.0.1:8420/security/secrets/key
```

Save the returned value as `SUDOBRAIN_SECRETS_KEY` in a private environment
channel. Secret names can then be listed without exposing values:

```bash
curl http://127.0.0.1:8420/security/secrets/status
curl http://127.0.0.1:8420/security/secrets
```

## Local Data

SudoBrain is designed to keep source copies and extracted knowledge in local
storage you control. Public bug reports should use synthetic or redacted data.
