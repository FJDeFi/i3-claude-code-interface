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
    argv = ssh_terminal.build_remote_command_argv()
    assert argv == ("/bin/bash", "-il")


def test_build_remote_command_with_api_key(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv()
    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "ANTHROPIC_API_KEY" in inner
    assert "exec" in inner and "claude" in inner


def test_build_remote_command_with_session_api_key(monkeypatch):
    monkeypatch.delenv("SSH_REMOTE_COMMAND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-secret")
    monkeypatch.setenv("CLAUDE_CODE_CMD", "claude")
    argv = ssh_terminal.build_remote_command_argv("sk-ant-session-secret")
    assert argv[0] == "bash" and argv[1] == "-lc"
    inner = argv[2]
    assert "sk-ant-session-secret" in inner
    assert "sk-ant-env-secret" not in inner
    assert "exec" in inner and "claude" in inner


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


def test_default_term_size(monkeypatch):
    monkeypatch.setenv("SSH_INITIAL_COLS", "999")
    monkeypatch.setenv("SSH_INITIAL_ROWS", "3")
    assert ssh_terminal._default_term_size() == (500, 5)
