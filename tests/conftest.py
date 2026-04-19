"""Shared fixtures: a fake tmux runner + isolated SQLite DB per test."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pytest


@dataclass
class FakeTmuxWorld:
    """In-memory stand-in for a tmux server.

    * Commands run through ``run`` and are recorded for assertions.
    * ``pipe-pane`` is emulated by having ``write_pane`` append bytes to the
      session's log file — exactly what a real pipe-pane would do.
    * ``has-session`` honours which sessions have been created.
    """

    log_paths: dict = field(default_factory=dict)
    sessions: set = field(default_factory=set)
    calls: List[List[str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def run(self, argv: List[str], *, input: Optional[str] = None) -> subprocess.CompletedProcess:
        with self.lock:
            self.calls.append(list(argv))

        stripped = [arg for arg in argv if arg != "tmux"]
        while stripped and stripped[0] == "-L":
            stripped = stripped[2:]

        if not stripped:
            return subprocess.CompletedProcess(argv, 1, "", "empty argv")

        verb = stripped[0]
        rest = stripped[1:]

        if verb == "new-session":
            session_name = rest[rest.index("-s") + 1] if "-s" in rest else None
            with self.lock:
                if session_name:
                    self.sessions.add(session_name)
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "pipe-pane":
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            session_name = target.split(":", 1)[0]
            # pipe command is the last arg; we parse the filename back out.
            pipe_command = rest[-1]
            # format: ``cat >> '/some/path'``
            if ">>" in pipe_command:
                quoted = pipe_command.split(">>", 1)[1].strip()
                if quoted.startswith("'") and quoted.endswith("'"):
                    quoted = quoted[1:-1].replace("'\\''", "'")
                self.log_paths[session_name] = Path(quoted)
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "has-session":
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            return subprocess.CompletedProcess(
                argv, 0 if target in self.sessions else 1, "", ""
            )

        if verb == "kill-session":
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            self.sessions.discard(target)
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "load-buffer":
            # ``input`` holds the text to paste; remember it for the next
            # paste-buffer call.
            self._buffer = input or ""
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "paste-buffer":
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            session_name = target.split(":", 1)[0]
            buf = getattr(self, "_buffer", "")
            self.write_pane(session_name, buf)
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "send-keys":
            # send Enter -> just emit a newline into the pane log for realism.
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            session_name = target.split(":", 1)[0]
            if "C-m" in rest:
                self.write_pane(session_name, "\n")
            return subprocess.CompletedProcess(argv, 0, "", "")

        if verb == "capture-pane":
            target = rest[rest.index("-t") + 1] if "-t" in rest else ""
            session_name = target.split(":", 1)[0]
            log_path = self.log_paths.get(session_name)
            content = log_path.read_text() if log_path and log_path.exists() else ""
            return subprocess.CompletedProcess(argv, 0, content, "")

        return subprocess.CompletedProcess(argv, 1, "", f"unknown verb {verb!r}")

    def write_pane(self, session_name: str, text: str) -> None:
        """Simulate pane output for a session (appends to its log)."""
        log_path = self.log_paths.get(session_name)
        if log_path is None:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            with log_path.open("ab") as handle:
                handle.write(text.encode())


@pytest.fixture
def fake_tmux() -> FakeTmuxWorld:
    return FakeTmuxWorld()


@pytest.fixture
def state_module(tmp_path, monkeypatch):
    """Reload ``app.state`` against a brand-new sqlite DB per test."""
    db_path = tmp_path / "chats.db"
    monkeypatch.setenv("CHAT_DB_PATH", str(db_path))

    for mod in ("app.state", "app.chat_session", "app.main"):
        sys.modules.pop(mod, None)

    module = importlib.import_module("app.state")
    return module


@pytest.fixture
def chat_module(state_module):
    module = importlib.import_module("app.chat_session")
    return module


@pytest.fixture
def tmux_module():
    return importlib.import_module("app.tmux_session")
