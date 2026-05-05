#!/bin/bash
set -euo pipefail

# Start the FastAPI SSH terminal bridge for Claude Code on a remote host.
export SSH_HOST="127.0.0.1"
export SSH_USER="romy_chen"
export SSH_PRIVATE_KEY_PATH="$HOME/.ssh/claude_bridge_ed25519"
export SSH_PORT="22"
export SSH_STRICT_HOST_KEY_CHECKING="yes"
export SSH_KNOWN_HOSTS="$HOME/.ssh/known_hosts_claude_bridge"

PORT="${PORT:-8000}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
