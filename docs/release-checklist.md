# Release Checklist

Use this before tagging a public release.

## Verify

- `make verify`
- `make release-readiness`
- `make smoke` against a running local backend
- `make demo` on a clean local database
- `curl http://127.0.0.1:8420/onboarding/status`
- `curl 'http://127.0.0.1:8420/knowledge/export?format=json'`

## Privacy And Safety

- Confirm `.env`, OAuth tokens, recordings, transcripts, and local data are not tracked.
- Run the public repo verifier.
- Check that external source sync defaults remain disabled in `.env.example`.
- Confirm any write-capable workflow is explicitly permissioned and auditable.

## Packaging

- Update `CHANGELOG.md`.
- Update `docs/roadmap.md` if roadmap status changed.
- Build the macOS app.
- Test `docker-compose.full.yml`.
- Run `make package` for an unsigned source/backend release archive.
- Attach release notes with known limitations.
- Keep `make release-readiness` green; external signing/GIF/docs-hosting blockers
  should be listed explicitly rather than hidden.

## Community

- Review issue templates.
- Mark small scoped tasks with `good-first-issue`.
- Keep docs aligned with the release tag.
