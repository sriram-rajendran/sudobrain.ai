#!/bin/bash
# Start the SudoBrain Python backend server
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Starting SudoBrain backend on http://127.0.0.1:8420"
echo "Press Ctrl+C to stop"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8420 --reload
