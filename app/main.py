"""FastAPI entrypoint: static UI, token-gated access, and WebSocket PTY bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ssh_terminal import run_terminal_bridge
from .token import create_token, list_tokens as redis_list_tokens, revoke_token, validate_token


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
    )
    return JSONResponse(created, status_code=201)


@app.delete("/api/tokens/{token}")
async def delete_token(token: str, request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    revoked = await revoke_token(token)
    if not revoked:
        return JSONResponse(status_code=404, content={"detail": "Token not found"})
    return JSONResponse({"status": "revoked", "token": token})
