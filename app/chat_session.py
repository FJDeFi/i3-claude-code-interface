"""ChatManager — the bridge between HTTP requests and tmux-backed Claude.

Each chat owns:

* a ``TmuxSession`` running ``CLAUDE_CODE_CMD`` (defaults to ``claude``),
* a persistent pipe-pane log file on disk,
* a background tail thread that reads new bytes from the log, strips ANSI
  escapes, and appends an ``assistant`` event for every delta.

Concurrent ``send_message`` calls on the same chat are serialized by a
per-chat lock so injected prompts cannot interleave.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from .state import (
    append_chat_event,
    clear_chat_api_key,
    get_chat,
    insert_chat,
    update_chat_status,
)
from .tmux_session import TmuxSession


_ANSI_PATTERN = re.compile(
    rb"\x1b\[[0-9;?]*[ -/]*[@-~]"   # CSI sequences
    rb"|\x1b\][^\x07]*(?:\x07|\x1b\\)"  # OSC sequences
    rb"|\x1b[=>]"                        # keypad modes
    rb"|\x1b\([AB012]"                   # charset selection
    rb"|[\x00-\x08\x0b\x0c\x0e-\x1f]"    # most control chars, keep \n, \r, \t
)


def strip_ansi(data: bytes) -> str:
    cleaned = _ANSI_PATTERN.sub(b"", data)
    return cleaned.decode("utf-8", errors="replace")


DEFAULT_LOG_DIR = Path(os.getenv("TMUX_LOG_DIR", "/tmp/claude-chat-logs"))
DEFAULT_PREFIX = os.getenv("TMUX_SESSION_PREFIX", "claude-chat-")
DEFAULT_CLAUDE_CMD = os.getenv("CLAUDE_CODE_CMD", "claude")


TmuxFactory = Callable[[str, Path], TmuxSession]


def _default_tmux_factory(session_name: str, log_path: Path) -> TmuxSession:
    return TmuxSession(session_name=session_name, log_path=log_path)


@dataclass
class ChatRuntime:
    chat_id: str
    tmux: TmuxSession
    log_path: Path
    read_offset: int = 0
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class ChatManager:
    def __init__(
        self,
        *,
        log_dir: Path = DEFAULT_LOG_DIR,
        prefix: str = DEFAULT_PREFIX,
        claude_cmd: str = DEFAULT_CLAUDE_CMD,
        tmux_factory: TmuxFactory = _default_tmux_factory,
        poll_interval: float = 0.3,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.claude_cmd = claude_cmd
        self.tmux_factory = tmux_factory
        self.poll_interval = poll_interval

        self._chats: Dict[str, ChatRuntime] = {}
        self._global_lock = threading.Lock()

    # ------------------------------------------------------------------ API

    def create_chat(self, *, anthropic_api_key: str) -> str:
        """Create a new tmux-backed chat authenticated by ``anthropic_api_key``.

        The key is handed to tmux via ``new-session -e ANTHROPIC_API_KEY=...``
        so it is only present in the pane's environment, never pasted as
        terminal input and never echoed into the pane's log. The key is also
        stored in SQLite scoped to this chat so the server could, if needed,
        restart the pane later — but it is never returned via any HTTP route.
        """

        if not anthropic_api_key or not anthropic_api_key.strip():
            raise ValueError("anthropic_api_key must not be empty")

        api_key = anthropic_api_key.strip()

        chat_id = uuid.uuid4().hex[:12]
        session_name = f"{self.prefix}{chat_id}"
        log_path = self.log_dir / f"{session_name}.log"

        # #region agent log
        from .agent_debug import agent_log

        agent_log(
            "chat_session.py:create_chat",
            "paths_ready",
            {
                "chat_id": chat_id,
                "session_name": session_name,
                "log_parent": str(log_path.parent),
                "log_parent_exists": log_path.parent.exists(),
                "claude_cmd": self.claude_cmd,
            },
            "H1-H4",
        )
        # #endregion

        tmux = self.tmux_factory(session_name, log_path)
        # #region agent log
        agent_log(
            "chat_session.py:create_chat",
            "before_tmux_start",
            {},
            "H1",
        )
        # #endregion
        tmux.start(
            command=self.claude_cmd,
            env={"ANTHROPIC_API_KEY": api_key},
        )
        # #region agent log
        agent_log(
            "chat_session.py:create_chat",
            "after_tmux_start",
            {},
            "H1-H2",
        )
        agent_log(
            "chat_session.py:create_chat",
            "before_insert_chat",
            {},
            "H3",
        )
        # #endregion

        insert_chat(chat_id, session_name, str(log_path), anthropic_api_key=api_key)
        append_chat_event(chat_id, "status", "session-started")
        append_chat_event(chat_id, "status", "launched:claude")

        runtime = ChatRuntime(chat_id=chat_id, tmux=tmux, log_path=log_path)
        with self._global_lock:
            self._chats[chat_id] = runtime

        self._start_tail(runtime)
        return chat_id

    def send_message(self, chat_id: str, text: str) -> None:
        runtime = self._require(chat_id)
        with runtime.send_lock:
            append_chat_event(chat_id, "user", text)
            runtime.tmux.send_text(text)

    def stop_chat(self, chat_id: str) -> None:
        with self._global_lock:
            runtime = self._chats.pop(chat_id, None)
        if not runtime:
            return
        runtime.stop_event.set()
        if runtime.thread is not None:
            runtime.thread.join(timeout=2)
        try:
            runtime.tmux.kill()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            append_chat_event(chat_id, "error", f"kill failed: {exc}")
        update_chat_status(chat_id, "stopped")
        clear_chat_api_key(chat_id)
        append_chat_event(chat_id, "status", "stopped")

    def is_active(self, chat_id: str) -> bool:
        with self._global_lock:
            return chat_id in self._chats

    def shutdown(self) -> None:
        with self._global_lock:
            chat_ids = list(self._chats.keys())
        for chat_id in chat_ids:
            self.stop_chat(chat_id)

    # --------------------------------------------------------------- internals

    def _require(self, chat_id: str) -> ChatRuntime:
        with self._global_lock:
            runtime = self._chats.get(chat_id)
        if runtime is None:
            if get_chat(chat_id) is None:
                raise KeyError(f"Unknown chat {chat_id!r}")
            raise RuntimeError(
                f"Chat {chat_id!r} is no longer active; start a new chat"
            )
        return runtime

    def _start_tail(self, runtime: ChatRuntime) -> None:
        def loop() -> None:
            while not runtime.stop_event.is_set():
                try:
                    delta = self._read_new_bytes(runtime)
                except Exception as exc:  # pragma: no cover - defensive
                    append_chat_event(
                        runtime.chat_id, "error", f"tail error: {exc}"
                    )
                    delta = b""

                if delta:
                    text = strip_ansi(delta)
                    if text.strip():
                        append_chat_event(
                            runtime.chat_id, "assistant", text
                        )

                runtime.stop_event.wait(self.poll_interval)

        thread = threading.Thread(
            target=loop, daemon=True, name=f"tail-{runtime.chat_id}"
        )
        runtime.thread = thread
        thread.start()

    @staticmethod
    def _read_new_bytes(runtime: ChatRuntime) -> bytes:
        if not runtime.log_path.exists():
            return b""
        with runtime.log_path.open("rb") as handle:
            handle.seek(runtime.read_offset)
            chunk = handle.read()
        runtime.read_offset += len(chunk)
        return chunk
