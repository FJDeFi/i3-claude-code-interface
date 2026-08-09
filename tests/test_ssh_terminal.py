"""Unit tests for SSH bridge configuration helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from app import ssh_terminal


def test_load_ssh_bridge_config_requires_host(monkeypatch, tmp_path):
    monkeypatch.delenv("SSH_HOST", raising=False)
    monkeypatch.delenv("SSH_USER", raising=False)
    monkeypatch.delenv("SSH_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(ValueError, match="SSH_HOST"):
        ssh_terminal.load_ssh_bridge_config()


def test_load_ssh_bridge_config_requires_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SSH_HOST", "example.com")
    monkeypatch.setenv("SSH_USER", "me")
    monkeypatch.setenv("SSH_PRIVATE_KEY_PATH", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="not a file"):
        ssh_terminal.load_ssh_bridge_config()


def test_load_ssh_bridge_config_ok(monkeypatch, tmp_path):
    key = tmp_path / "id_rsa"
    key.write_text("fake-key\n")
    monkeypatch.setenv("SSH_HOST", "example.com")
    monkeypatch.setenv("SSH_USER", "deploy")
    monkeypatch.setenv("SSH_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setenv("SSH_PORT", "2222")
    monkeypatch.delenv("SSH_KNOWN_HOSTS", raising=False)
    cfg = ssh_terminal.load_ssh_bridge_config()
    assert cfg.host == "example.com"
    assert cfg.username == "deploy"
    assert cfg.port == 2222
    assert cfg.client_key_path == Path(key)


def test_argv_to_remote_exec_string_joins_with_shlex():
    s = ssh_terminal.argv_to_remote_exec_string(("bash", "-lc", "echo hi; date"))
    assert s.startswith("bash -lc ")
    assert "echo hi" in s


def test_build_remote_command_login_shell(monkeypatch):
    for k in (
        "SSH_REMOTE_COMMAND",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_CMD",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENCLAW_ENV_FILE", "/tmp/i3-claude-code-interface-missing.env")
    argv = ssh_terminal.build_remote_command_argv()
    assert argv == ("/bin/bash", "-il")


def test_build_remote_command_with_api_key(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.delenv("OPENCLAW_ENV_FILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv()
    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "ANTHROPIC_API_KEY" in inner
    assert "exec" in inner and "claude" in inner


def test_build_remote_command_with_openclaw_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / "openclaw.env"
    env_file.write_text("OPENAI_API_KEY=unused\nANTHROPIC_API_KEY=sk-ant-file-secret\n")
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENCLAW_ENV_FILE", str(env_file))
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv()
    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "sk-ant-file-secret" in inner
    assert "exec" in inner and "claude" in inner


def test_build_remote_command_with_session_api_key(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.delenv("OPENCLAW_ENV_FILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-secret")
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv("sk-ant-session-secret")
    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "sk-ant-session-secret" in inner
    assert "sk-ant-env-secret" not in inner
    assert "exec" in inner and "claude" in inner


def test_build_remote_command_with_glm_key(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv(
        "glm-session-secret",
        provider="glm",
    )
    inner = argv[2]
    assert "ANTHROPIC_AUTH_TOKEN=glm-session-secret" in inner
    assert "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic" in inner
    assert "API_TIMEOUT_MS=3000000" in inner
    assert "ANTHROPIC_API_KEY" not in inner
    assert "exec claude" in inner


def test_build_remote_command_tmux_creates_detached_without_status(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.delenv("OPENCLAW_ENV_FILE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv(
        "sk-ant-session-secret",
        tmux_session="demo",
        root_dir="/workspace",
    )

    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "tmux new-session -d -s demo -c /workspace" in inner
    assert "tmux set-option -t demo status off" in inner
    assert "tmux attach -t demo" in inner
    assert "if tmux has-session -t demo" in inner


def test_build_remote_command_tmux_read_only_attach(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.delenv("OPENCLAW_ENV_FILE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv(
        "sk-ant-session-secret",
        tmux_session="demo",
        root_dir="/workspace",
        read_only=True,
    )

    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "tmux attach -r -t demo" in inner
    assert "tmux new-session" not in inner
    assert "ANTHROPIC_API_KEY" not in inner


def test_build_remote_command_custom_remote(monkeypatch):
    monkeypatch.setenv("SSH_REMOTE_COMMAND", "vim")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    argv = ssh_terminal.build_remote_command_argv()
    assert argv[0] == "bash" and argv[1] == "-lc"
    assert "vim" in argv[2]


def test_try_parse_resize():
    assert ssh_terminal._try_parse_resize("not json") is None
    assert ssh_terminal._try_parse_resize('{"type":"resize","cols":100,"rows":30}') == (
        100,
        30,
    )


def test_try_parse_tmux_scroll():
    assert ssh_terminal._try_parse_tmux_scroll("not json") is None
    assert ssh_terminal._try_parse_tmux_scroll('{"type":"resize","cols":100,"rows":30}') is None
    assert ssh_terminal._try_parse_tmux_scroll('{"type":"tmux-scroll","direction":"left"}') is None
    assert ssh_terminal._try_parse_tmux_scroll('{"type":"tmux-scroll","direction":"up","lines":4}') == (
        "up",
        4,
    )
    assert ssh_terminal._try_parse_tmux_scroll('{"type":"tmux-scroll","direction":"down","lines":999}') == (
        "down",
        50,
    )


def test_try_parse_tmux_copy_mode_cancel():
    assert ssh_terminal._try_parse_tmux_copy_mode_cancel("not json") is False
    assert ssh_terminal._try_parse_tmux_copy_mode_cancel('{"type":"tmux-scroll","direction":"up"}') is False
    assert ssh_terminal._try_parse_tmux_copy_mode_cancel('{"type":"tmux-copy-mode","action":"cancel"}') is True


def test_scroll_tmux_session_uses_copy_mode(monkeypatch):
    calls = []

    class FakeProc:
        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(ssh_terminal._scroll_tmux_session("demo", "up", 5))

    assert calls == [
        ("tmux", "copy-mode", "-t", "demo"),
        ("tmux", "send-keys", "-t", "demo", "-N", "5", "-X", "scroll-up"),
    ]


def test_cancel_tmux_copy_mode(monkeypatch):
    calls = []

    class FakeProc:
        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    asyncio.run(ssh_terminal._cancel_tmux_copy_mode("demo"))

    assert calls == [
        ("tmux", "send-keys", "-t", "demo", "-X", "cancel"),
    ]


def test_receive_start_api_key_without_key_returns_none():
    class FakeWebSocket:
        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": '{"type":"start"}',
                },
            ]

        async def receive(self):
            if not self.messages:
                raise WebSocketDisconnect()
            return self.messages.pop(0)

    api_key = asyncio.run(ssh_terminal._receive_start_api_key(FakeWebSocket()))
    assert api_key is None


def test_receive_start_api_key_ignores_initial_resize():
    class FakeWebSocket:
        def __init__(self):
            self.messages = [
                {
                    "type": "websocket.receive",
                    "text": '{"type":"resize","cols":100,"rows":30}',
                },
                {
                    "type": "websocket.receive",
                    "text": '{"type":"start","anthropic_api_key":" sk-ant-session "}',
                },
            ]

        async def receive(self):
            if not self.messages:
                raise WebSocketDisconnect()
            return self.messages.pop(0)

    api_key = asyncio.run(ssh_terminal._receive_start_api_key(FakeWebSocket()))
    assert api_key == "sk-ant-session"


def test_receive_start_with_glm_provider():
    class FakeWebSocket:
        async def receive(self):
            return {
                "type": "websocket.receive",
                "text": '{"type":"start","provider":"glm","api_key":" glm-secret ","session":"demo"}',
            }

    start = asyncio.run(ssh_terminal.receive_terminal_start(FakeWebSocket()))
    assert start == ("glm-secret", "demo", None, "glm", "claude")


def test_receive_start_rejects_unknown_provider():
    class FakeWebSocket:
        async def receive(self):
            return {
                "type": "websocket.receive",
                "text": '{"type":"start","provider":"custom","api_key":"secret","session":"demo"}',
            }

    start = asyncio.run(ssh_terminal.receive_terminal_start(FakeWebSocket()))
    assert start == ("secret", "demo", None, "anthropic", "claude")


def test_build_remote_command_with_codex_key(monkeypatch):
    monkeypatch.setenv("CODEX_CMD", "codex")
    argv = ssh_terminal.build_remote_command_argv(
        "sk-openai-secret",
        tmux_session="codex-demo",
        root_dir="/workspace",
        provider="openai",
        agent="codex",
    )
    inner = argv[2]
    assert "OPENAI_API_KEY=sk-openai-secret" in inner
    assert 'CODEX_HOME="$HOME/.codex-i3/codex-demo"' in inner
    assert "codex login --with-api-key" in inner
    assert "exec codex" in inner
    assert "ANTHROPIC_API_KEY" not in inner


def test_default_term_size(monkeypatch):
    monkeypatch.setenv("SSH_INITIAL_COLS", "999")
    monkeypatch.setenv("SSH_INITIAL_ROWS", "3")
    assert ssh_terminal._default_term_size() == (500, 5)
