# SSH Terminal Bridge — Implementation

The web UI loads **xterm.js** in the browser and opens a **WebSocket** to this
server. The server uses **asyncssh** to connect to a remote host (credentials
from environment variables only), allocates a **PTY**, and copies I/O between
the WebSocket and the remote process so the user can run **Claude Code** (or
any shell) interactively on the remote machine.

## Architecture

```mermaid
flowchart LR
  browser[xterm.js] <-->|WebSocket| api[FastAPI]
  api --> ssh[asyncssh]
  ssh --> remote[Remote PTY]
```

### Key files

- [`app/ssh_terminal.py`](app/ssh_terminal.py) — Loads `SSH_*` settings from
  the environment, connects with a client key, builds the remote command
  (`build_remote_command_argv`), and runs `_bridge_loop` to copy bytes and
  handle `{"type":"resize","cols","rows"}` JSON messages from the client.
- [`app/main.py`](app/main.py) — Serves static UI, `GET /health`, and
  `WebSocket /ws/terminal`.
- [`app/static/`](app/static/) — HTML/CSS and client script that wires xterm
  to the WebSocket (binary frames for terminal data, text JSON for resize).

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SSH_HOST` | yes | Remote hostname or IP |
| `SSH_USER` | yes | SSH username |
| `SSH_PRIVATE_KEY_PATH` | yes | Path to private key on the server running uvicorn |
| `SSH_PORT` | no | Default `22` |
| `SSH_STRICT_HOST_KEY_CHECKING` | no | `yes`/`no` (default yes) |
| `SSH_KNOWN_HOSTS` | no | Path to known_hosts when strict checking is on |
| `SSH_REMOTE_COMMAND` | no | If set, remote runs `bash -lc` with this command after optional `ANTHROPIC_API_KEY` export |
| `ANTHROPIC_API_KEY` | no | If set without `SSH_REMOTE_COMMAND`, remote runs `bash -lc` that exports the key and `exec`s `CLAUDE_CODE_CMD` |
| `CLAUDE_CODE_CMD` | no | Default `claude` |
| `SSH_TERM_TYPE` | no | Default `xterm-256color` |
| `SSH_INITIAL_COLS` / `SSH_INITIAL_ROWS` | no | Initial PTY size before the client sends resize |

### Security

This service can reach any host the SSH key allows. Run it behind TLS, limit
network access, and treat the host like a bastion.

### Tests

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest tests/ -q
```
