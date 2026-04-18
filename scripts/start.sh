#!/bin/bash
set -euo pipefail

# start API
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# start worker
python3 -c "from app.worker import worker_loop; worker_loop()" &
WORKER_PID=$!

echo "Web UI available at http://127.0.0.1:8000"

cleanup() {
  kill "$API_PID" "$WORKER_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
wait -n "$API_PID" "$WORKER_PID"
