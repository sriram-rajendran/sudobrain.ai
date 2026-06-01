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
- Review extracted actions, decisions, and promises before using them for
  operational decisions.
- Rotate credentials immediately if they were committed or shared.

## Local Data

SudoBrain is designed to keep source copies and extracted knowledge in local
storage you control. Public bug reports should use synthetic or redacted data.
