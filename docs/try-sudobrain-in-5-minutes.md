# Try SudoBrain In 5 Minutes

This path uses only local services and synthetic data.

## 1. Bootstrap

```bash
./scripts/bootstrap_local.sh
```

## 2. Start The Backend

```bash
./run_backend.sh
```

## 3. Load Demo Data

In another terminal:

```bash
make demo
```

## 4. Verify

```bash
make smoke
curl 'http://127.0.0.1:8420/search?q=Atlas'
curl 'http://127.0.0.1:8420/knowledge/export?format=markdown'
```

## 5. Open The App

```bash
./run_app.sh
```

Use Onboarding to inspect service health, Chat to ask about Atlas Launch, People
to view synthetic contacts, and Decisions or Promises to inspect extracted work
memory.
