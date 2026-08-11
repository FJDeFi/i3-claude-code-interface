#!/bin/bash
set -euo pipefail

# New single-VM deployments run tmux as the service user and do not need to
# SSH back into themselves. Set CLAUDE_CODE_LOCAL_TMUX=false to retain the
# remote-SSH deployment mode.
export CLAUDE_CODE_LOCAL_TMUX="${CLAUDE_CODE_LOCAL_TMUX:-true}"

if [[ "$CLAUDE_CODE_LOCAL_TMUX" =~ ^([Ff][Aa][Ll][Ss][Ee]|0|[Nn][Oo])$ ]]; then
  export SSH_HOST="${SSH_HOST:-127.0.0.1}"
  export SSH_USER="${SSH_USER:-$(id -un)}"
  export SSH_PRIVATE_KEY_PATH="${SSH_PRIVATE_KEY_PATH:-$HOME/.ssh/claude_bridge_ed25519}"
  export SSH_PORT="${SSH_PORT:-22}"
  export SSH_STRICT_HOST_KEY_CHECKING="${SSH_STRICT_HOST_KEY_CHECKING:-yes}"
  export SSH_KNOWN_HOSTS="${SSH_KNOWN_HOSTS:-$HOME/.ssh/known_hosts_claude_bridge}"
fi

# The official standalone installer places Codex here. Non-interactive login
# shells do not consistently load ~/.bashrc, so put it on PATH explicitly.
export PATH="$HOME/.local/bin:$PATH"

if [[ "${CODEX_AUTO_INSTALL:-true}" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])$ ]]; then
  bash "$(dirname "$0")/install-codex.sh"
fi

if [[ -z "${CODEX_CMD:-}" ]] && command -v codex >/dev/null 2>&1; then
  export CODEX_CMD="$(command -v codex)"
fi

PORT="${PORT:-8000}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
