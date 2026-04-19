#!/bin/bash
set -euo pipefail

# Start the FastAPI tmux-backed Claude Code bridge.
PORT="${PORT:-8000}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
