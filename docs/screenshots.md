# Screenshot And GIF Checklist

The README includes synthetic public-safe SVG screenshots and a generated demo
GIF. Before a polished public launch, replace them with captured screenshots or
GIFs from the demo app.

Capture these views with synthetic demo data:

- Today
- Chat with citation cards
- Knowledge Graph
- People
- Decisions
- Workflows with templates and approvals
- Reports
- Source Sync freshness
- Models provider configuration
- Admin dashboard

Suggested output folder:

```bash
docs/assets/screenshots/
```

Regenerate the public-safe animated GIF:

```bash
make demo-gif
```

Keep screenshots synthetic. Do not include real names, emails, transcripts,
customer data, source code, tokens, or private project names.
