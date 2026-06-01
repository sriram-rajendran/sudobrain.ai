#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

docker compose up -d postgres neo4j

echo "Local setup complete."
echo "Start the backend with: ./run_backend.sh"
echo "Load synthetic demo data after the backend DB is healthy with: make demo"
