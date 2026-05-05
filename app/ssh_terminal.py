"""WebSocket bridge from the browser to a remote PTY over SSH (asyncssh).

SSH target and authentication are read only from environment variables
(see ``load_ssh_bridge_config``). The browser never receives credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

import asyncssh
from asyncssh import PIPE, STDOUT
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)
START_MESSAGE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class SshBridgeConfig:
    host: str
    port: int
    username: str
    client_key_path: Path
    known_hosts_path: Optional[Path]
    strict_host_key_checking: bool


def load_ssh_bridge_config() -> SshBridgeConfig:
    host = os.getenv("SSH_HOST", "").strip()
    user = os.getenv("SSH_USER", "").strip()
    key_path_raw = os.getenv("SSH_PRIVATE_KEY_PATH", "").strip()
    if not host:
        raise ValueError("SSH_HOST is not set")
    if not user:
        raise ValueError("SSH_USER is not set")
    if not key_path_raw:
        raise ValueError("SSH_PRIVATE_KEY_PATH is not set")
    key_path = Path(key_path_raw).expanduser()
    if not key_path.is_file():
        raise ValueError(f"SSH_PRIVATE_KEY_PATH is not a file: {key_path}")

    port_s = os.getenv("SSH_PORT", "22").strip()
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ValueError("SSH_PORT must be an integer") from exc

    strict = os.getenv("SSH_STRICT_HOST_KEY_CHECKING", "yes").strip().lower() in (
        "1",
        "yes",
        "true",
    )
    known_raw = os.getenv("SSH_KNOWN_HOSTS", "").strip()
    known: Optional[Path] = None
    if known_raw:
        known = Path(known_raw).expanduser()

    return SshBridgeConfig(
        host=host,
        port=port,
        username=user,
        client_key_path=key_path,
        known_hosts_path=known,
        strict_host_key_checking=strict,
    )


def build_remote_command_argv(api_key: Optional[str] = None) -> Tuple[str, ...]:
    """Return argv for the remote process (executed under a PTY).

    * If ``SSH_REMOTE_COMMAND`` is set, run ``bash -lc`` with optional
      ``ANTHROPIC_API_KEY`` / ``CLAUDE_CODE_CMD`` exports prepended.
    * Otherwise, if ``ANTHROPIC_API_KEY`` is set, run ``bash -lc`` that
      exports the key and ``exec``'s ``CLAUDE_CODE_CMD`` (default ``claude``).
    * Otherwise start an interactive login shell.
    """

    remote_cmd = os.getenv("SSH_REMOTE_COMMAND", "").strip()
    effective_api_key = (
        api_key.strip() if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "").strip()
    )
    claude_cmd = os.getenv("CLAUDE_CODE_CMD", "claude").strip() or "claude"

    parts: List[str] = []
    if effective_api_key:
        parts.append(f"export ANTHROPIC_API_KEY={shlex.quote(effective_api_key)}")
    if remote_cmd:
        parts.append(remote_cmd)
        inner = "; ".join(parts)
        return ("bash", "-lc", inner)
    if effective_api_key:
        parts.append(f"exec {shlex.quote(claude_cmd)}")
        inner = "; ".join(parts)
        return ("bash", "-lc", inner)
    return ("/bin/bash", "-il")


def argv_to_remote_exec_string(argv: Tuple[str, ...]) -> str:
    """Turn argv into one remote exec string for AsyncSSH.

    Passing ``command=`` as a tuple of length > 2 triggers a bug in some AsyncSSH
    versions (logging assumes 2-tuples are host/port).
    """

    return " ".join(shlex.quote(part) for part in argv)


def _known_hosts_argument(cfg: SshBridgeConfig) -> Any:
    if not cfg.strict_host_key_checking:
        return None
    if cfg.known_hosts_path and cfg.known_hosts_path.is_file():
        return str(cfg.known_hosts_path)
    return ()


async def run_terminal_bridge(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        cfg = load_ssh_bridge_config()
    except ValueError as exc:
        await websocket.send_text(
            json.dumps({"type": "error", "message": str(exc)})
        )
        await websocket.close(code=4400)
        return

    try:
        api_key = await _receive_start_api_key(websocket)
    except WebSocketDisconnect:
        return
    cols, rows = _default_term_size()
    try:
        conn = await asyncssh.connect(
            cfg.host,
            port=cfg.port,
            username=cfg.username,
            client_keys=[str(cfg.client_key_path)],
            known_hosts=_known_hosts_argument(cfg),
        )
    except (OSError, asyncssh.Error) as exc:
        await websocket.send_text(
            json.dumps({"type": "error", "message": f"SSH connect failed: {exc}"})
        )
        await websocket.close(code=4401)
        return

    argv = build_remote_command_argv(api_key)
    remote_exec = argv_to_remote_exec_string(argv)
    try:
        async with conn.create_process(
            command=remote_exec,
            stdin=PIPE,
            stdout=PIPE,
            stderr=STDOUT,
            term_type=os.getenv("SSH_TERM_TYPE", "xterm-256color"),
            term_size=(cols, rows),
            encoding=None,
        ) as process:
            await _bridge_loop(websocket, process, cols, rows)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("terminal bridge session failed")
        with contextlib.suppress(Exception):
            await websocket.send_text(
                json.dumps({"type": "error", "message": f"Server error: {exc}"})
            )
    finally:
        conn.close()
        await conn.wait_closed()


async def _receive_start_api_key(websocket: WebSocket) -> Optional[str]:
    """Read the initial WebSocket start message containing the session API key."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + START_MESSAGE_TIMEOUT_SECONDS
    while True:
        timeout = deadline - loop.time()
        if timeout <= 0:
            return None
        try:
            message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect()
        if message.get("type") != "websocket.receive":
            continue

        text = message.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "start":
            continue
        api_key = payload.get("anthropic_api_key")
        if not isinstance(api_key, str):
            return None
        return api_key.strip() or None


def _default_term_size() -> Tuple[int, int]:
    try:
        cols = int(os.getenv("SSH_INITIAL_COLS", "120"))
        rows = int(os.getenv("SSH_INITIAL_ROWS", "36"))
    except ValueError:
        return 120, 36
    return max(20, min(cols, 500)), max(5, min(rows, 200))


async def _bridge_loop(
    websocket: WebSocket,
    process: asyncssh.SSHClientProcess[bytes],
    cols: int,
    rows: int,
) -> None:
    current_cols, current_rows = cols, rows

    async def pump_out() -> None:
        assert process.stdout is not None
        while True:
            chunk = await process.stdout.read(65536)
            if not chunk:
                return
            await websocket.send_bytes(chunk)

    async def pump_in() -> None:
        nonlocal current_cols, current_rows
        while True:
            message = await websocket.receive()
            mtype = message.get("type")
            if mtype == "websocket.disconnect":
                return
            if mtype != "websocket.receive":
                continue
            if "bytes" in message and message["bytes"] is not None:
                process.stdin.write(message["bytes"])
                await process.stdin.drain()
            elif "text" in message and message["text"] is not None:
                resized = _try_parse_resize(message["text"])
                if resized:
                    current_cols, current_rows = resized
                    process.change_terminal_size(
                        current_cols, current_rows, 0, 0
                    )

    out_task = asyncio.create_task(pump_out())
    in_task = asyncio.create_task(pump_in())
    wait_task = asyncio.create_task(process.wait())
    try:
        done, pending = await asyncio.wait(
            {out_task, in_task, wait_task},
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
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        for task in (out_task, in_task, wait_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        with contextlib.suppress(Exception):
            process.stdin.write_eof()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=2.0)


def _try_parse_resize(text: str) -> Optional[Tuple[int, int]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "resize":
        return None
    try:
        cols = int(payload["cols"])
        rows = int(payload["rows"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(20, min(cols, 500)), max(5, min(rows, 200))
