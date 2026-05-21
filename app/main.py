"""FastAPI entrypoint: static UI, token-gated access, and WebSocket PTY bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ssh_terminal import run_terminal_bridge
from .token import create_token, get_token_record, list_tokens as redis_list_tokens, revoke_token, validate_token
import re
import shlex
import subprocess


app = FastAPI(title="Claude Code SSH terminal bridge")
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _read_static_html(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _render_html(name: str, *, session: Optional[dict] = None) -> HTMLResponse:
    html = _read_static_html(name)
    if session is not None:
        injected = f"<script>window.__CLAUDE_CODE_SESSION__ = {json.dumps(session)};</script>"
        html = html.replace("</body>", f"{injected}\n</body>", 1)
    return HTMLResponse(html)


def _extract_token_from_request(request: Request) -> str:
    query = request.query_params
    token = (
        query.get("claudecodeToken")
        or query.get("token")
        or request.headers.get("x-claude-code-token")
        or request.headers.get("x-claudecode-token")
    )
    if token:
        return token.strip()

    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


async def _resolve_session(request: Request) -> Optional[dict]:
    token = _extract_token_from_request(request)
    if not token:
        return None
    record = await validate_token(token)
    if not record:
        return None
    return {"token": token, **record}


async def _require_privileged_session(request: Request) -> Optional[dict]:
    session = await _resolve_session(request)
    if not session:
        return None
    if session.get("role") not in {"owner", "administrator", "admin"}:
        return None
    return session


@app.get("/", include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    session = await _resolve_session(request)
    if not session:
        return _render_html("rejected.html")
    return _render_html("index.html", session=session)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ws/terminal", include_in_schema=False)
def ws_terminal_http_only() -> JSONResponse:
    """Plain HTTP GET hits this path when the WebSocket upgrade was stripped."""
    return JSONResponse(
        status_code=426,
        content={
            "detail": "This path is WebSocket-only. Configure your reverse proxy to pass Upgrade and Connection headers.",
        },
    )


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    token = (
        websocket.query_params.get("claudecodeToken")
        or websocket.query_params.get("token")
        or ""
    ).strip()
    session = await validate_token(token) if token else None
    if not session:
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Access denied: invalid or expired token"})
        )
        await websocket.close(code=4403)
        return

    # Block guest tokens that only have viewer access from opening a terminal
    if session.get("role") == "guest" and session.get("accessType", "viewer") == "viewer":
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Access denied: viewer tokens cannot use the terminal"})
        )
        await websocket.close(code=4403)
        return

    websocket.state.token_meta = session
    await run_terminal_bridge(websocket)


@app.get("/api/tokens")
async def get_tokens(request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    tokens = await redis_list_tokens()
    return JSONResponse({"tokens": tokens})


@app.post("/api/tokens")
async def create_guest_token(request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})

    body = await request.json()
    access_type = str(body.get("accessType") or "viewer").strip().lower()
    if access_type not in {"viewer", "editor"}:
        return JSONResponse(status_code=400, content={"detail": "accessType must be viewer or editor"})

    ttl_value = body.get("ttlSeconds")
    ttl_seconds: Optional[int] = None
    if ttl_value not in (None, "", 0, "0"):
        try:
            ttl_seconds = int(ttl_value)
        except (TypeError, ValueError):
            return JSONResponse(status_code=400, content={"detail": "ttlSeconds must be an integer"})
        if ttl_seconds <= 0:
            return JSONResponse(status_code=400, content={"detail": "ttlSeconds must be greater than zero"})

    created = await create_token(
        access_type=access_type,
        ttl_seconds=ttl_seconds,
        role="guest",
        created_by=session["token"],
        session=(lambda s: (','.join(s) if isinstance(s, list) else str(s)))(body.get('session')) if body.get('session') is not None else None,
    )
    return JSONResponse(created, status_code=201)


@app.delete("/api/tokens/{token}")
async def delete_token(token: str, request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    record = await get_token_record(token)
    if record and record.get("role") == "owner":
        return JSONResponse(status_code=403, content={"detail": "Owner tokens cannot be revoked"})
    revoked = await revoke_token(token)
    if not revoked:
        return JSONResponse(status_code=404, content={"detail": "Token not found"})
    return JSONResponse({"status": "revoked", "token": token})


def _safe_session_name(name: str) -> bool:
    # Allow only alnum, underscore, hyphen
    return bool(re.match(r'^[A-Za-z0-9_\-]+$', name))


def _run_cmd(cmd: str) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=False)
        return (completed.returncode, completed.stdout or "", completed.stderr or "")
    except Exception as e:
        return (255, "", str(e))


@app.get("/api/claudecode/sessions")
async def list_claudecode_sessions(request: Request) -> JSONResponse:
    # Determine caller: privileged session or a token-based session
    priv = await _require_privileged_session(request)
    token_param = _extract_token_from_request(request)
    token_record = None
    if token_param:
        token_record = await validate_token(token_param)

    # If caller is neither privileged nor presenting a token, require auth
    if not priv and not token_record:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token or valid claude token required"})

    # Run tmux ls
    rc, out, err = _run_cmd("tmux ls")
    sessions = []
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split(":", 1)
            if parts:
                sessions.append(parts[0])

    # If token_record present and not privileged, filter sessions by token->session mapping
    if token_record and not priv:
        allowed = token_record.get("session") or "*"
        if allowed != "*":
            allowed_set = {s.strip() for s in allowed.split(",") if s.strip()}
            sessions = [s for s in sessions if s in allowed_set]

    return JSONResponse({"sessions": sessions})


@app.post("/api/claudecode/sessions")
async def create_claudecode_session(request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})

    body = await request.json()
    name = str(body.get("name") or "").strip()
    path = body.get("path") or None
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Session name required"})
    if not _safe_session_name(name):
        return JSONResponse(status_code=400, content={"detail": "Invalid session name"})

    cmd = f"tmux new -d -s {shlex.quote(name)}"
    if path:
        cmd = f"tmux new -d -s {shlex.quote(name)} -c {shlex.quote(path)}"

    rc, out, err = _run_cmd(cmd)
    if rc != 0:
        return JSONResponse(status_code=500, content={"detail": "Failed to create session", "error": err})
    return JSONResponse({"name": name})


@app.delete("/api/claudecode/sessions/{name}")
async def delete_claudecode_session(name: str, request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    if not _safe_session_name(name):
        return JSONResponse(status_code=400, content={"detail": "Invalid session name"})

    rc, out, err = _run_cmd(f"tmux kill-session -t {shlex.quote(name)}")
    if rc != 0:
        return JSONResponse(status_code=500, content={"detail": "Failed to delete session", "error": err})
    return JSONResponse({"deleted": name})
