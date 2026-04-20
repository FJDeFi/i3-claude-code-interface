"""Thin wrapper around the tmux CLI for a single-window session.

The class intentionally keeps a very small surface:

* ``start`` creates a detached tmux session and wires ``pipe-pane`` to a log
  file so the entire pane stdout is persisted to disk.
* ``send_text`` injects arbitrary text (including multi-line) using the
  ``load-buffer`` / ``paste-buffer`` / ``send-keys`` pattern recommended in
  ``scripts/tmux-monitor.sh``.
* ``kill`` tears the session down.

All tmux invocations go through a single ``runner`` callable so tests can
substitute a fake implementation without a real tmux binary.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


RunnerResult = subprocess.CompletedProcess
Runner = Callable[..., RunnerResult]


def _default_runner(argv: List[str], *, input: Optional[str] = None) -> RunnerResult:
    return subprocess.run(
        argv,
        input=input,
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass
class TmuxSession:
    """Represents one tmux session with its pane streamed to ``log_path``."""

    session_name: str
    log_path: Path
    runner: Runner = field(default=_default_runner)
    socket_name: Optional[str] = None
    paste_delay: float = 0.1

    def _argv(self, *args: str) -> List[str]:
        argv: List[str] = ["tmux"]
        if self.socket_name:
            argv += ["-L", self.socket_name]
        argv += list(args)
        return argv

    def _tmux(self, *args: str, stdin: Optional[str] = None) -> RunnerResult:
        return self.runner(self._argv(*args), input=stdin)

    # ------------------------------------------------------------------ API

    def exists(self) -> bool:
        result = self._tmux("has-session", "-t", self.session_name)
        return result.returncode == 0

    def start(
        self,
        command: Optional[str] = None,
        *,
        width: int = 220,
        height: int = 50,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Create the session and start piping the pane into ``log_path``.

        ``env`` entries are passed to ``tmux new-session`` as ``-e KEY=VALUE``
        pairs so secrets are set on the pane's environment *without* ever being
        pasted as visible terminal input.
        """

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_bytes(b"")

        new_session_args: List[str] = [
            "new-session",
            "-d",
            "-s",
            self.session_name,
            "-x",
            str(width),
            "-y",
            str(height),
        ]
        if env:
            for key, value in env.items():
                new_session_args += ["-e", f"{key}={value}"]
        if command:
            new_session_args.append(command)

        result = self._tmux(*new_session_args)
        # #region agent log
        from .agent_debug import agent_log

        err_tail = ((result.stderr or result.stdout) or "").strip()[:500]
        agent_log(
            "tmux_session.py:start",
            "new_session_done",
            {"returncode": result.returncode, "stderr_head": err_tail},
            "H1",
        )
        # #endregion
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start tmux session {self.session_name!r}: "
                f"{(result.stderr or result.stdout).strip()}"
            )

        # ``pipe-pane`` streams every byte written to the pane into our log.
        # The shell command runs in the user's default shell, so we pass a
        # plain ``cat`` redirection; tmux does the quoting for us.
        pipe_command = f"cat >> {self._shell_quote(str(self.log_path))}"
        result = self._tmux(
            "pipe-pane",
            "-o",
            "-t",
            f"{self.session_name}:0",
            pipe_command,
        )
        # #region agent log
        err_tail2 = ((result.stderr or result.stdout) or "").strip()[:500]
        agent_log(
            "tmux_session.py:start",
            "pipe_pane_done",
            {"returncode": result.returncode, "stderr_head": err_tail2},
            "H2",
        )
        # #endregion
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to enable pipe-pane for {self.session_name!r}: "
                f"{(result.stderr or result.stdout).strip()}"
            )

    def send_text(self, text: str, *, press_enter: bool = True) -> None:
        """Inject ``text`` into the pane using load-buffer + paste-buffer."""

        load = self._tmux("load-buffer", "-", stdin=text)
        if load.returncode != 0:
            raise RuntimeError(
                f"load-buffer failed: {(load.stderr or load.stdout).strip()}"
            )

        paste = self._tmux("paste-buffer", "-t", f"{self.session_name}:0")
        if paste.returncode != 0:
            raise RuntimeError(
                f"paste-buffer failed: {(paste.stderr or paste.stdout).strip()}"
            )

        if press_enter:
            if self.paste_delay > 0:
                time.sleep(self.paste_delay)
            enter = self._tmux(
                "send-keys", "-t", f"{self.session_name}:0", "C-m"
            )
            if enter.returncode != 0:
                raise RuntimeError(
                    f"send-keys C-m failed: "
                    f"{(enter.stderr or enter.stdout).strip()}"
                )

    def capture_pane(self) -> str:
        result = self._tmux(
            "capture-pane", "-p", "-J", "-t", f"{self.session_name}:0"
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"capture-pane failed: {(result.stderr or result.stdout).strip()}"
            )
        return result.stdout or ""

    def kill(self) -> None:
        self._tmux("kill-session", "-t", self.session_name)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _shell_quote(value: str) -> str:
        return "'" + value.replace("'", "'\\''") + "'"
