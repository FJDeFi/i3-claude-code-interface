"""FastAPI entrypoint: static UI, token-gated access, and WebSocket PTY bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .collab import (
    approve_control_request,
    ensure_collab_state,
    get_collab_state,
    request_control,
    transfer_control,
)
from .ssh_terminal import receive_terminal_start, run_terminal_bridge
from .logging_setup import setup_logger
from .firebase_auth import verify_owner_id_token
from .terminal_hub import TerminalHub
from .token import (
    create_token,
    create_web_session,
    get_token_record,
    list_tokens as redis_list_tokens,
    revoke_token,
    revoke_web_session,
    update_token_session,
    validate_token,
    validate_web_session,
)
import os
import time
import re
import shlex
import subprocess


app = FastAPI(title="Claude Code SSH terminal bridge")
STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = setup_logger("claude_code.api")
SESSION_COOKIE = "claude_code_session"
terminal_hub = TerminalHub()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _read_static_html(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _render_html(name: str, *, session: Optional[dict] = None) -> HTMLResponse:
    html = _read_static_html(name)
    if session is not None:
        session_json = (
            json.dumps(session)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        injected = f"<script>window.__CLAUDE_CODE_SESSION__ = {session_json};</script>"
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


def _mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return token
    return f"{token[:4]}…{token[-4:]}"


async def _resolve_session(request: Request) -> Optional[dict]:
    web_session_id = request.cookies.get(SESSION_COOKIE, "").strip()
    if web_session_id:
        web_session = await validate_web_session(web_session_id)
        if web_session:
            return {"webSessionId": web_session_id, **web_session}

    token = _extract_token_from_request(request)
    if not token:
        return None
    record = await validate_token(token)
    if not record:
        return None
    return {"token": token, **record}


async def _resolve_websocket_session(websocket: WebSocket) -> Optional[dict]:
    web_session_id = websocket.cookies.get(SESSION_COOKIE, "").strip()
    if web_session_id:
        web_session = await validate_web_session(web_session_id)
        if web_session:
            return {"webSessionId": web_session_id, **web_session}

    token = (
        websocket.query_params.get("claudecodeToken")
        or websocket.query_params.get("token")
        or ""
    ).strip()
    token_session = await validate_token(token) if token else None
    if token_session:
        return {"token": token, **token_session}
    return None


def _cookie_secure(request: Request) -> bool:
    configured = os.getenv("CLAUDE_SESSION_COOKIE_SECURE", "true").strip().lower()
    if configured in {"0", "false", "no"}:
        return False
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return request.url.scheme == "https" or forwarded == "https" or configured == "true"


async def _require_privileged_session(request: Request) -> Optional[dict]:
    session = await _resolve_session(request)
    if not session:
        return None
    if session.get("role") not in {"owner", "administrator", "admin"}:
        return None
    return session


def _session_actor_id(session: dict) -> str:
    token = str(session.get("token") or "").strip()
    if token:
        return f"token:{token}"
    web_session_id = str(session.get("webSessionId") or "").strip()
    if web_session_id:
        return f"web:{web_session_id}"
    uid = str(session.get("uid") or "").strip()
    if uid:
        return f"uid:{uid}"
    return f"session:{id(session)}"


def _session_actor_label(session: dict) -> str:
    display = str(session.get("displayName") or "").strip()
    email = str(session.get("email") or "").strip()
    if display:
        return display
    if email:
        return email
    token = str(session.get("token") or "").strip()
    if token:
        return f"{session.get('role', 'guest')} {_mask_token(token)}"
    return str(session.get("role") or "user")


def _is_privileged(session: dict) -> bool:
    return session.get("role") in {"owner", "administrator", "admin"}


def _session_can_access_tmux(session: dict, tmux_session: str) -> bool:
    if _is_privileged(session):
        return True
    allowed = str(session.get("session") or "*").strip()
    if allowed == "*":
        return True
    allowed_set = {s.strip() for s in allowed.split(",") if s.strip()}
    return tmux_session in allowed_set


async def _collab_payload(tmux_session: str, session: dict) -> Optional[dict]:
    state = await get_collab_state(tmux_session)
    if state is None:
        return None
    actor_id = _session_actor_id(session)
    is_master = actor_id == state.get("masterId")
    is_controller = actor_id == state.get("controllerId")
    role = "viewer"
    if is_master:
        role = "master-controller" if is_controller else "master"
    elif is_controller:
        role = "controller"
    return {
        **state,
        "actorId": actor_id,
        "actorLabel": _session_actor_label(session),
        "isMaster": is_master,
        "isController": is_controller,
        "collabRole": role,
        "participants": terminal_hub.participants(tmux_session),
    }


async def _ensure_collab_for_privileged(
    tmux_session: str,
    session: dict,
) -> Optional[dict]:
    state = await get_collab_state(tmux_session)
    if state is not None:
        return state
    if not _is_privileged(session):
        return None
    return await ensure_collab_state(
        tmux_session,
        master_id=_session_actor_id(session),
        master_label=_session_actor_label(session),
    )


async def _send_viewer_stream(
    websocket: WebSocket,
    *,
    tmux_session: str,
    session: dict,
) -> None:
    actor_id = _session_actor_id(session)
    terminal_hub.add_participant(
        tmux_session,
        actor_id=actor_id,
        label=_session_actor_label(session),
        role="viewer",
        websocket=websocket,
    )
    queue = terminal_hub.subscribe(tmux_session)
    payload = await _collab_payload(tmux_session, session)
    if payload:
        await websocket.send_text(json.dumps({"type": "collab", "state": payload}))

    async def pump_out() -> None:
        while True:
            chunk = await queue.get()
            await websocket.send_bytes(chunk)

    async def pump_in() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return

    out_task = asyncio.create_task(pump_out())
    in_task = asyncio.create_task(pump_in())
    try:
        done, pending = await asyncio.wait(
            {out_task, in_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        terminal_hub.unsubscribe(tmux_session, queue)
        terminal_hub.remove_participant(tmux_session, actor_id)
        for task in (out_task, in_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


@app.get("/", include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    session = await _resolve_session(request)
    if not session:
        logger.info("GET / rejected", extra={"token": _mask_token(_extract_token_from_request(request))})
        return _render_html("rejected.html")
    logger.info("GET / ok", extra={"token": _mask_token(session.get("token", "")), "role": session.get("role")})
    return _render_html("index.html", session=session)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/firebase")
async def firebase_login(request: Request) -> JSONResponse:
    body = await request.json()
    firebase_token = str(body.get("idToken") or "").strip()
    try:
        claims = verify_owner_id_token(firebase_token)
    except PermissionError as exc:
        logger.warning("Firebase owner login denied")
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except Exception as exc:
        logger.warning("Firebase token verification failed: %s", exc)
        return JSONResponse(status_code=401, content={"detail": "Invalid Firebase authentication"})

    ttl_seconds = 3600
    try:
        expires_at = int(claims.get("exp") or 0)
        if expires_at:
            ttl_seconds = min(3600, max(60, expires_at - int(time.time())))
    except (TypeError, ValueError):
        pass

    session_id, session = await create_web_session(
        uid=str(claims.get("sub") or claims.get("user_id") or ""),
        email=claims.get("email"),
        display_name=claims.get("name"),
        ttl_seconds=ttl_seconds,
    )
    response = JSONResponse({
        "status": "authenticated",
        "user": {
            "uid": session.get("uid"),
            "email": session.get("email"),
            "displayName": session.get("displayName"),
        },
    })
    secure_cookie = _cookie_secure(request)
    same_site = "none" if secure_cookie else "lax"
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure_cookie,
        samesite=same_site,
        path="/",
    )
    if secure_cookie:
        response.headers["set-cookie"] = f'{response.headers["set-cookie"]}; Partitioned'
    return response


@app.post("/api/auth/logout")
async def firebase_logout(request: Request) -> JSONResponse:
    session_id = request.cookies.get(SESSION_COOKIE, "").strip()
    if session_id:
        await revoke_web_session(session_id)
    response = JSONResponse({"status": "signed_out"})
    secure_cookie = _cookie_secure(request)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=secure_cookie,
        samesite="none" if secure_cookie else "lax",
    )
    if secure_cookie:
        response.headers["set-cookie"] = f'{response.headers["set-cookie"]}; Partitioned'
    return response


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
    session = await _resolve_websocket_session(websocket)
    if not session:
        logger.info("WS /ws/terminal denied")
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Access denied: invalid or expired token"})
        )
        await websocket.close(code=4403)
        return

    logger.info(
        "WS /ws/terminal accepted",
        extra={"role": session.get("role"), "access": session.get("accessType")},
    )
    websocket.state.token_meta = session
    await websocket.accept()
    try:
        start = await receive_terminal_start(websocket)
    except Exception:
        await websocket.close(code=4400)
        return
    tmux_session = start[1] if isinstance(start, tuple) else None
    if not tmux_session:
        await websocket.send_text(json.dumps({"type": "error", "message": "Select a session before connecting"}))
        await websocket.close(code=4400)
        return
    if not _session_can_access_tmux(session, tmux_session):
        await websocket.send_text(json.dumps({"type": "error", "message": "Access denied for this session"}))
        await websocket.close(code=4403)
        return

    state = await _ensure_collab_for_privileged(tmux_session, session)
    if state is None:
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Session has no master yet. Ask the owner to open it first."})
        )
        await websocket.close(code=4403)
        return

    actor_id = _session_actor_id(session)
    is_controller = actor_id == state.get("controllerId")
    if not is_controller:
        await _send_viewer_stream(websocket, tmux_session=tmux_session, session=session)
        return

    role = "master-controller" if actor_id == state.get("masterId") else "controller"
    terminal_hub.add_participant(
        tmux_session,
        actor_id=actor_id,
        label=_session_actor_label(session),
        role=role,
        websocket=websocket,
    )
    payload = await _collab_payload(tmux_session, session)
    if payload:
        await websocket.send_text(json.dumps({"type": "collab", "state": payload}))
    try:
        await run_terminal_bridge(
            websocket,
            start=start,
            accept=False,
            output_callback=lambda chunk: terminal_hub.broadcast(tmux_session, chunk),
        )
    finally:
        terminal_hub.remove_participant(tmux_session, actor_id)


@app.get("/api/tokens")
async def get_tokens(request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        logger.info("GET /api/tokens denied", extra={"token": _mask_token(_extract_token_from_request(request))})
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    logger.info("GET /api/tokens ok", extra={"token": _mask_token(session.get("token", ""))})
    tokens = await redis_list_tokens()
    return JSONResponse({"tokens": tokens})


@app.post("/api/tokens")
async def create_guest_token(request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        logger.info("POST /api/tokens denied", extra={"token": _mask_token(_extract_token_from_request(request))})
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

    logger.info(
        "POST /api/tokens",
        extra={
            "token": _mask_token(session.get("token", "")),
            "access": access_type,
            "ttl": ttl_seconds,
            "session": str(body.get("session") or "*"),
        },
    )
    created = await create_token(
        access_type=access_type,
        ttl_seconds=ttl_seconds,
        role="guest",
        created_by=session.get("token") or _session_actor_id(session),
        session=(lambda s: (','.join(s) if isinstance(s, list) else str(s)))(body.get('session')) if body.get('session') is not None else None,
    )
    return JSONResponse(created, status_code=201)


@app.delete("/api/tokens/{token}")
async def delete_token(token: str, request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        logger.info("DELETE /api/tokens denied", extra={"token": _mask_token(_extract_token_from_request(request))})
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    record = await get_token_record(token)
    if record and record.get("role") == "owner":
        logger.info("DELETE /api/tokens blocked owner", extra={"token": _mask_token(token)})
        return JSONResponse(status_code=403, content={"detail": "Owner tokens cannot be revoked"})
    revoked = await revoke_token(token)
    if not revoked:
        logger.info("DELETE /api/tokens not found", extra={"token": _mask_token(token)})
        return JSONResponse(status_code=404, content={"detail": "Token not found"})
    logger.info("DELETE /api/tokens ok", extra={"token": _mask_token(token)})
    return JSONResponse({"status": "revoked", "token": token})


@app.patch("/api/tokens/{token}")
async def update_token(token: str, request: Request) -> JSONResponse:
    session = await _require_privileged_session(request)
    if not session:
        logger.info("PATCH /api/tokens denied", extra={"token": _mask_token(_extract_token_from_request(request))})
        return JSONResponse(status_code=403, content={"detail": "Owner/admin token required"})
    body = await request.json()
    session_value = body.get("session")
    if isinstance(session_value, list):
        session_value = ",".join([str(s).strip() for s in session_value if str(s).strip()])
    if isinstance(session_value, str):
        session_value = session_value.strip() or "*"
    logger.info(
        "PATCH /api/tokens",
        extra={"token": _mask_token(token), "session": session_value},
    )
    updated = await update_token_session(token, session_value)
    if not updated:
        logger.info("PATCH /api/tokens not found", extra={"token": _mask_token(token)})
        return JSONResponse(status_code=404, content={"detail": "Token not found or not editable"})
    return JSONResponse(updated)


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

    name_q = shlex.quote(name)
    cmd = f"tmux new -d -s {name_q}"
    if path:
        cmd = f"tmux new -d -s {name_q} -c {shlex.quote(path)}"

    rc, out, err = _run_cmd(cmd)
    if rc != 0:
        return JSONResponse(status_code=500, content={"detail": "Failed to create session", "error": err})
    _run_cmd(f"tmux set-option -t {name_q} status off")
    await ensure_collab_state(
        name,
        master_id=_session_actor_id(session),
        master_label=_session_actor_label(session),
    )
    return JSONResponse({"name": name})


@app.get("/api/claudecode/sessions/{name}/collab")
async def get_session_collab(name: str, request: Request) -> JSONResponse:
    session = await _resolve_session(request)
    if not session or not _safe_session_name(name) or not _session_can_access_tmux(session, name):
        return JSONResponse(status_code=403, content={"detail": "Valid session access required"})
    await _ensure_collab_for_privileged(name, session)
    payload = await _collab_payload(name, session)
    if payload is None:
        return JSONResponse(status_code=404, content={"detail": "Collaboration state has not been initialized"})
    return JSONResponse(payload)


@app.post("/api/claudecode/sessions/{name}/request-control")
async def request_session_control(name: str, request: Request) -> JSONResponse:
    session = await _resolve_session(request)
    if not session or not _safe_session_name(name) or not _session_can_access_tmux(session, name):
        return JSONResponse(status_code=403, content={"detail": "Valid session access required"})
    state = await request_control(
        name,
        actor_id=_session_actor_id(session),
        actor_label=_session_actor_label(session),
    )
    if state is None:
        return JSONResponse(status_code=404, content={"detail": "Collaboration state has not been initialized"})
    payload = await _collab_payload(name, session)
    return JSONResponse(payload or state)


def _participant_label(name: str, actor_id: str) -> str:
    for participant in terminal_hub.participants(name):
        if participant.get("actorId") == actor_id:
            return participant.get("label") or "Controller"
    return "Controller"


@app.post("/api/claudecode/sessions/{name}/approve-control")
async def approve_session_control(name: str, request: Request) -> JSONResponse:
    session = await _resolve_session(request)
    if not session or not _safe_session_name(name) or not _session_can_access_tmux(session, name):
        return JSONResponse(status_code=403, content={"detail": "Valid session access required"})
    body = await request.json()
    requester_id = str(body.get("actorId") or "").strip()
    result = await approve_control_request(
        name,
        master_id=_session_actor_id(session),
        requester_id=requester_id,
    )
    if result is None:
        return JSONResponse(status_code=403, content={"detail": "Only the master can approve pending requests"})
    state, old_controller_id = result
    await terminal_hub.close_actor(name, old_controller_id)
    await terminal_hub.close_actor(name, requester_id)
    payload = await _collab_payload(name, session)
    return JSONResponse(payload or state)


@app.post("/api/claudecode/sessions/{name}/transfer-control")
async def transfer_session_control(name: str, request: Request) -> JSONResponse:
    session = await _resolve_session(request)
    if not session or not _safe_session_name(name) or not _session_can_access_tmux(session, name):
        return JSONResponse(status_code=403, content={"detail": "Valid session access required"})
    body = await request.json()
    target_id = str(body.get("actorId") or "").strip()
    if not target_id:
        return JSONResponse(status_code=400, content={"detail": "actorId is required"})
    result = await transfer_control(
        name,
        master_id=_session_actor_id(session),
        target_id=target_id,
        target_label=str(body.get("label") or _participant_label(name, target_id)),
    )
    if result is None:
        return JSONResponse(status_code=403, content={"detail": "Only the master can transfer control"})
    state, old_controller_id = result
    await terminal_hub.close_actor(name, old_controller_id)
    await terminal_hub.close_actor(name, target_id)
    payload = await _collab_payload(name, session)
    return JSONResponse(payload or state)


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
