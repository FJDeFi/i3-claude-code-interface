#!/bin/bash
set -euo pipefail

# Start the FastAPI SSH terminal bridge for Claude Code on a remote host.
PORT="${PORT:-8000}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
