#!/bin/bash
set -euo pipefail

# Install OpenAI Codex for the account that will own the tmux sessions.
# Safe to run repeatedly: an existing installation is left untouched.
export PATH="$HOME/.local/bin:$PATH"

if command -v codex >/dev/null 2>&1; then
  printf 'Codex CLI already installed: %s\n' "$(command -v codex)"
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  printf 'Cannot install Codex CLI: curl is not installed.\n' >&2
  exit 1
fi

printf 'Installing OpenAI Codex CLI for user %s...\n' "$(id -un)"
curl -fsSL https://chatgpt.com/codex/install.sh | sh

if [[ ! -x "$HOME/.local/bin/codex" ]]; then
  printf 'Codex installer completed, but %s was not created.\n' "$HOME/.local/bin/codex" >&2
  exit 1
fi

"$HOME/.local/bin/codex" --version
