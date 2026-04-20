"""Integration tests for ChatManager with a fake tmux runner."""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def _make_manager(tmp_path, fake_tmux, chat_module, tmux_module, claude_cmd="claude-fake"):
    log_dir = tmp_path / "logs"

    def factory(session_name: str, log_path: Path):
        return tmux_module.TmuxSession(
            session_name=session_name,
            log_path=log_path,
            runner=fake_tmux.run,
            paste_delay=0.0,
        )

    return chat_module.ChatManager(
        log_dir=log_dir,
        prefix="test-",
        claude_cmd=claude_cmd,
        tmux_factory=factory,
        poll_interval=0.05,
    )


def _wait_for(predicate, timeout=2.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


TEST_API_KEY = "sk-ant-test-0123456789"


def test_create_chat_spawns_session_and_records_status(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)

        assert state_module.get_chat(chat_id) is not None
        assert manager.is_active(chat_id)
        session_name = state_module.get_chat(chat_id).tmux_session
        assert session_name in fake_tmux.sessions

        events = state_module.list_events_after(chat_id)
        roles = [e.role for e in events]
        assert "status" in roles
        # The recorded "launched" status must not include the raw key.
        for event in events:
            assert TEST_API_KEY not in event.content
    finally:
        manager.shutdown()


def test_create_chat_rejects_empty_key(
    tmp_path, fake_tmux, chat_module, tmux_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        with pytest.raises(ValueError):
            manager.create_chat(anthropic_api_key="")
        with pytest.raises(ValueError):
            manager.create_chat(anthropic_api_key="   ")
    finally:
        manager.shutdown()


def test_create_chat_passes_api_key_as_tmux_env(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)
        session_name = state_module.get_chat(chat_id).tmux_session

        new_session_call = next(
            call for call in fake_tmux.calls
            if "new-session" in call and session_name in call
        )
        # tmux received -e ANTHROPIC_API_KEY=<key>
        assert "-e" in new_session_call
        env_arg_idx = new_session_call.index("-e") + 1
        assert new_session_call[env_arg_idx] == f"ANTHROPIC_API_KEY={TEST_API_KEY}"

        # Internal accessor round-trips the key for the chat lifetime.
        assert state_module.get_chat_api_key(chat_id) == TEST_API_KEY
    finally:
        manager.shutdown()


def test_stop_chat_clears_stored_api_key(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)
    assert state_module.get_chat_api_key(chat_id) == TEST_API_KEY
    manager.stop_chat(chat_id)
    assert state_module.get_chat_api_key(chat_id) is None


def test_send_message_injects_and_streams_output(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)
        session_name = state_module.get_chat(chat_id).tmux_session

        # Simulate Claude replying in the pane asynchronously.
        def reply_later():
            time.sleep(0.05)
            fake_tmux.write_pane(session_name, "Claude says hello\n")

        import threading
        threading.Thread(target=reply_later, daemon=True).start()

        manager.send_message(chat_id, "ping")

        got_user = _wait_for(
            lambda: any(
                e.role == "user" and e.content == "ping"
                for e in state_module.list_events_after(chat_id)
            )
        )
        got_assistant = _wait_for(
            lambda: any(
                "Claude says hello" in e.content
                for e in state_module.list_events_after(chat_id)
                if e.role == "assistant"
            )
        )
        assert got_user
        assert got_assistant
    finally:
        manager.shutdown()


def test_send_message_unknown_chat_raises(tmp_path, fake_tmux, chat_module, tmux_module):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        with pytest.raises(KeyError):
            manager.send_message("does-not-exist", "hi")
    finally:
        manager.shutdown()


def test_stop_chat_is_idempotent_and_kills_session(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)
    session_name = state_module.get_chat(chat_id).tmux_session

    manager.stop_chat(chat_id)
    assert session_name not in fake_tmux.sessions
    assert not manager.is_active(chat_id)
    assert state_module.get_chat(chat_id).status == "stopped"

    # second stop should not raise even though the chat is gone
    manager.stop_chat(chat_id)


def test_strip_ansi_removes_escape_sequences(chat_module):
    raw = b"\x1b[31mred\x1b[0m plain\r\n"
    cleaned = chat_module.strip_ansi(raw)
    assert "red plain" in cleaned
    assert "\x1b" not in cleaned


def test_concurrent_sends_are_serialized_per_chat(
    tmp_path, fake_tmux, chat_module, tmux_module, state_module
):
    manager = _make_manager(tmp_path, fake_tmux, chat_module, tmux_module)
    try:
        chat_id = manager.create_chat(anthropic_api_key=TEST_API_KEY)
        import threading

        def send(text):
            manager.send_message(chat_id, text)

        threads = [threading.Thread(target=send, args=(f"msg-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        user_events = [
            e for e in state_module.list_events_after(chat_id) if e.role == "user"
        ]
        assert sorted(e.content for e in user_events) == [
            "msg-0", "msg-1", "msg-2", "msg-3", "msg-4"
        ]
    finally:
        manager.shutdown()
