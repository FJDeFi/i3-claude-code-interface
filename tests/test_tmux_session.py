"""Unit tests for the tmux command wrapper."""

from __future__ import annotations

from pathlib import Path


def test_start_creates_session_and_pipes_log(tmp_path, fake_tmux, tmux_module):
    log_path = tmp_path / "logs" / "session.log"
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=log_path,
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    tmux.start(command="echo hi")

    assert "demo" in fake_tmux.sessions
    assert fake_tmux.log_paths["demo"] == log_path
    assert log_path.exists()

    verbs = [call[1] if call[0] == "tmux" else call[0] for call in fake_tmux.calls]
    assert "new-session" in verbs
    assert "pipe-pane" in verbs


def test_send_text_uses_paste_buffer_sequence(tmp_path, fake_tmux, tmux_module):
    log_path = tmp_path / "session.log"
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=log_path,
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    tmux.start()
    fake_tmux.calls.clear()

    tmux.send_text("hello world")

    sequence = [call[1] for call in fake_tmux.calls]
    assert sequence == ["load-buffer", "paste-buffer", "send-keys"]
    # Pane log should now contain the injected text followed by enter.
    assert log_path.read_text().endswith("hello world\n")


def test_send_text_without_enter_does_not_press_return(tmp_path, fake_tmux, tmux_module):
    log_path = tmp_path / "session.log"
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=log_path,
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    tmux.start()
    fake_tmux.calls.clear()

    tmux.send_text("no enter", press_enter=False)

    verbs = [call[1] for call in fake_tmux.calls]
    assert "send-keys" not in verbs


def test_exists_reflects_session_lifecycle(tmp_path, fake_tmux, tmux_module):
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=tmp_path / "log",
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    assert tmux.exists() is False
    tmux.start()
    assert tmux.exists() is True
    tmux.kill()
    assert tmux.exists() is False


def test_start_raises_when_runner_fails(tmp_path, tmux_module):
    import subprocess

    def failing_runner(argv, *, input=None):
        return subprocess.CompletedProcess(argv, 1, "", "boom")

    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=tmp_path / "log",
        runner=failing_runner,
        paste_delay=0.0,
    )
    import pytest

    with pytest.raises(RuntimeError):
        tmux.start()


def test_start_passes_env_via_new_session_flag(tmp_path, fake_tmux, tmux_module):
    log_path = tmp_path / "session.log"
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=log_path,
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    tmux.start(command="claude", env={"ANTHROPIC_API_KEY": "sk-test"})

    new_session_call = next(
        call for call in fake_tmux.calls
        if "new-session" in call
    )
    assert "-e" in new_session_call
    idx = new_session_call.index("-e") + 1
    assert new_session_call[idx] == "ANTHROPIC_API_KEY=sk-test"
    # The key must not be pasted as terminal input (no load-buffer call yet).
    verbs = [c[1] for c in fake_tmux.calls]
    assert "load-buffer" not in verbs
    # The key must also not end up in the pane log because it was passed via -e.
    assert "sk-test" not in log_path.read_text()


def test_capture_pane_returns_log_contents(tmp_path, fake_tmux, tmux_module):
    log_path = tmp_path / "session.log"
    tmux = tmux_module.TmuxSession(
        session_name="demo",
        log_path=log_path,
        runner=fake_tmux.run,
        paste_delay=0.0,
    )
    tmux.start()
    fake_tmux.write_pane("demo", "first line\n")
    fake_tmux.write_pane("demo", "second line\n")

    assert "first line" in tmux.capture_pane()
    assert "second line" in tmux.capture_pane()
