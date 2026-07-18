"""WebSocket bridge from the browser to a remote PTY over SSH (asyncssh).

SSH target and authentication are read only from environment variables
(see ``load_ssh_bridge_config``). The browser never receives credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import pty
import shlex
import signal
import struct
import termios
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Tuple, Union

import asyncssh
from asyncssh import PIPE, STDOUT
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .logging_setup import setup_logger

logger = setup_logger("claude_code.ssh")
START_MESSAGE_TIMEOUT_SECONDS = 3.0
OPENCLAW_ENV_FILE = Path("/etc/openclaw.env")
OutputCallback = Callable[[bytes], Awaitable[None]]


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


def build_remote_command_argv(
    api_key: Optional[str] = None,
    tmux_session: Optional[str] = None,
    root_dir: Optional[str] = None,
    read_only: bool = False,
) -> Tuple[str, ...]:
    """Return argv for the remote process (executed under a PTY).

    * If ``SSH_REMOTE_COMMAND`` is set, run ``bash -lc`` with optional
      ``ANTHROPIC_API_KEY`` / ``CLAUDE_CODE_CMD`` exports prepended.
    * Otherwise, if ``ANTHROPIC_API_KEY`` is set, run ``bash -lc`` that
      exports the key and ``exec``'s ``CLAUDE_CODE_CMD`` (default ``claude``).
    * Otherwise start an interactive login shell.
    """

    remote_cmd = os.getenv("SSH_REMOTE_COMMAND", "").strip()
    effective_api_key = _resolve_anthropic_api_key(api_key)
    claude_cmd = os.getenv("CLAUDE_CODE_CMD", "claude").strip() or "claude"

    if tmux_session:
        session_q = shlex.quote(tmux_session)
        root_q = shlex.quote(root_dir) if root_dir else ""
        if read_only:
            attach_read_only = (
                f"tmux set-option -t {session_q} status off 2>/dev/null || true; "
                f"exec tmux attach -r -t {session_q}"
            )
            return ("bash", "-lc", attach_read_only)

        tmux_create_prefix = f"tmux new-session -d -s {session_q} {f'-c {root_q} ' if root_dir else ''}"

        if remote_cmd:
            if effective_api_key:
                inner = f"export ANTHROPIC_API_KEY={shlex.quote(effective_api_key)}; {remote_cmd}"
                create_new = f"{tmux_create_prefix}bash -lc {shlex.quote(inner)}"
            else:
                create_new = f"{tmux_create_prefix}bash -lc {shlex.quote(remote_cmd)}"
        elif effective_api_key:
            root_arg = f" --root {root_q}" if root_dir else ""
            inner = f"export ANTHROPIC_API_KEY={shlex.quote(effective_api_key)}; exec {shlex.quote(claude_cmd)}{root_arg}"
            create_new = f"{tmux_create_prefix}bash -lc {shlex.quote(inner)}"
        else:
            create_new = f"{tmux_create_prefix}/bin/bash -il"

        # Attach if it exists, otherwise create a session and run the command inside it.
        # Hide the tmux status bar so the browser terminal looks like a normal Claude session.
        attach_cmd = f"tmux attach -t {session_q}"
        attach_existing = (
            f"tmux set-option -t {session_q} status off 2>/dev/null; "
            f"{attach_cmd}"
        )
        new_cmd = (
            f"{create_new} && "
            f"(tmux set-option -t {session_q} status off 2>/dev/null || true); "
            f"{attach_cmd}"
        )
        attach_or_create = (
            f"tmux set-option -g status off 2>/dev/null; "
            f"if tmux has-session -t {session_q} 2>/dev/null; "
            f"then {attach_existing}; "
            f"else {new_cmd}; "
            f"fi"
        )
        return ("bash", "-lc", attach_or_create)

    parts: List[str] = []
    if effective_api_key:
        parts.append(f"export ANTHROPIC_API_KEY={shlex.quote(effective_api_key)}")
    if remote_cmd:
        parts.append(remote_cmd)
        inner = "; ".join(parts)
        return ("bash", "-lc", inner)
    if effective_api_key:
        root_arg = f" --root {shlex.quote(root_dir)}" if root_dir else ""
        parts.append(f"exec {shlex.quote(claude_cmd)}{root_arg}")
        inner = "; ".join(parts)
        return ("bash", "-lc", inner)
    return ("/bin/bash", "-il")


def _resolve_anthropic_api_key(api_key: Optional[str] = None) -> str:
    """Resolve the key from the browser, service env, or OpenClaw env file."""

    if api_key is not None:
        return api_key.strip()

    env_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key

    env_file = Path(os.getenv("OPENCLAW_ENV_FILE", str(OPENCLAW_ENV_FILE))).expanduser()
    return _read_env_file_value(env_file, "ANTHROPIC_API_KEY") or ""


def _read_env_file_value(path: Path, name: str) -> Optional[str]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None

    prefix = f"{name}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value.strip() or None
    return None


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


async def run_terminal_bridge(
    websocket: WebSocket,
    *,
    start: Optional["StartPayload"] = None,
    output_callback: Optional[OutputCallback] = None,
    accept: bool = True,
    read_only: bool = False,
) -> None:
    if accept:
        await websocket.accept()
    if start is None:
        try:
            start = await receive_terminal_start(websocket)
        except WebSocketDisconnect:
            return
    # start can be a tuple (api_key, tmux_session, root_dir) or just api_key
    if isinstance(start, tuple):
        api_key, tmux_session, root_dir = start
    else:
        api_key, tmux_session, root_dir = start, None, None

    if os.getenv("CLAUDE_CODE_LOCAL_TMUX", "").strip().lower() in {"1", "true", "yes"}:
        await _run_local_terminal_bridge(
            websocket,
            api_key,
            tmux_session,
            root_dir,
            output_callback=output_callback,
            read_only=read_only,
        )
        return

    try:
        cfg = load_ssh_bridge_config()
    except ValueError as exc:
        logger.info("ssh config error", extra={"error": str(exc)})
        await websocket.send_text(
            json.dumps({"type": "error", "message": str(exc)})
        )
        await websocket.close(code=4400)
        return

    logger.info(
        "ssh start tmux_session=%s root_dir=%s api_key=%s",
        tmux_session or "",
        root_dir or "",
        "present" if api_key else "missing",
    )
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

    argv = build_remote_command_argv(
        api_key,
        tmux_session=tmux_session,
        root_dir=root_dir,
        read_only=read_only,
    )
    remote_exec = argv_to_remote_exec_string(argv)
    logger.info(
        "ssh remote command tmux_session=%s root_dir=%s argv=%s",
        tmux_session or "",
        root_dir or "",
        " ".join(argv),
    )
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
            await _bridge_loop(
                websocket,
                process,
                cols,
                rows,
                output_callback=output_callback,
                read_only=read_only,
            )
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


async def _run_local_terminal_bridge(
    websocket: WebSocket,
    api_key: Optional[str],
    tmux_session: Optional[str],
    root_dir: Optional[str],
    *,
    output_callback: Optional[OutputCallback] = None,
    read_only: bool = False,
) -> None:
    cols, rows = _default_term_size()
    argv = build_remote_command_argv(
        api_key,
        tmux_session=tmux_session,
        root_dir=root_dir,
        read_only=read_only,
    )
    logger.info(
        "local terminal command tmux_session=%s root_dir=%s argv=%s",
        tmux_session or "",
        root_dir or "",
        " ".join(argv),
    )
    try:
        await _local_pty_bridge(
            websocket,
            argv,
            cols,
            rows,
            output_callback=output_callback,
            read_only=read_only,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("local terminal bridge session failed")
        with contextlib.suppress(Exception):
            await websocket.send_text(
                json.dumps({"type": "error", "message": f"Server error: {exc}"})
            )


async def _local_pty_bridge(
    websocket: WebSocket,
    argv: Tuple[str, ...],
    cols: int,
    rows: int,
    *,
    output_callback: Optional[OutputCallback] = None,
    read_only: bool = False,
) -> None:
    master_fd, slave_fd = pty.openpty()
    _set_pty_size(slave_fd, cols, rows)
    child_env = {
        **os.environ,
        "TERM": os.getenv("SSH_TERM_TYPE", "xterm-256color"),
    }
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=child_env,
        start_new_session=True,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    async def pump_out() -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                chunk = await loop.run_in_executor(None, os.read, master_fd, 65536)
            except BlockingIOError:
                await asyncio.sleep(0.01)
                continue
            except OSError:
                return
            if not chunk:
                return
            await websocket.send_bytes(chunk)
            if output_callback is not None:
                await output_callback(chunk)

    async def pump_in() -> None:
        while True:
            message = await websocket.receive()
            mtype = message.get("type")
            if mtype == "websocket.disconnect":
                return
            if read_only:
                continue
            if mtype != "websocket.receive":
                continue
            if "bytes" in message and message["bytes"] is not None:
                os.write(master_fd, message["bytes"])
            elif "text" in message and message["text"] is not None:
                resized = _try_parse_resize(message["text"])
                if resized:
                    new_cols, new_rows = resized
                    _set_pty_size(master_fd, new_cols, new_rows)

    out_task = asyncio.create_task(pump_out())
    in_task = asyncio.create_task(pump_in())
    wait_task = asyncio.create_task(proc.wait())
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
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGHUP)
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            os.close(master_fd)


def _set_pty_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


StartPayload = Union[str, Tuple[Optional[str], Optional[str], Optional[str]]]


async def receive_terminal_start(websocket: WebSocket) -> Optional[StartPayload]:
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
        # Optional tmux session name for attaching to a shared session
        tmux_session = payload.get("session")
        root_dir = payload.get("rootDir")
        api_key_val = api_key.strip() or None if isinstance(api_key, str) else None
        tmux_val = tmux_session.strip() if isinstance(tmux_session, str) else None
        root_val = root_dir.strip() if isinstance(root_dir, str) and root_dir.strip() else None
        if tmux_val:
            return (api_key_val, tmux_val, root_val)
        return api_key_val


_receive_start_api_key = receive_terminal_start


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
    *,
    output_callback: Optional[OutputCallback] = None,
    read_only: bool = False,
) -> None:
    current_cols, current_rows = cols, rows

    async def pump_out() -> None:
        assert process.stdout is not None
        while True:
            chunk = await process.stdout.read(65536)
            if not chunk:
                return
            await websocket.send_bytes(chunk)
            if output_callback is not None:
                await output_callback(chunk)

    async def pump_in() -> None:
        nonlocal current_cols, current_rows
        while True:
            message = await websocket.receive()
            mtype = message.get("type")
            if mtype == "websocket.disconnect":
                return
            if read_only:
                continue
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
