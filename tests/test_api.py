"""End-to-end API tests using FastAPI TestClient + fake tmux world."""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_API_KEY = "sk-ant-test-0123456789"


def _create_chat(http):
    response = http.post("/chats", json={"anthropic_api_key": TEST_API_KEY})
    assert response.status_code == 200, response.text
    return response.json()["chat_id"]


def _wait_for(predicate, timeout=2.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def client(tmp_path, monkeypatch, fake_tmux, state_module):
    # state_module fixture already set CHAT_DB_PATH + reloaded state.
    # Now import main and override its ChatManager to use the fake runner.
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    tmux_module = importlib.import_module("app.tmux_session")
    chat_module = importlib.import_module("app.chat_session")

    def factory(session_name: str, log_path: Path):
        return tmux_module.TmuxSession(
            session_name=session_name,
            log_path=log_path,
            runner=fake_tmux.run,
            paste_delay=0.0,
        )

    manager = chat_module.ChatManager(
        log_dir=tmp_path / "logs",
        prefix="api-test-",
        claude_cmd="fake-claude",
        tmux_factory=factory,
        poll_interval=0.05,
    )
    main.app.state.chat_manager = manager

    with TestClient(main.app) as client:
        yield client, manager, fake_tmux

    manager.shutdown()


def test_health_endpoint(client):
    http, _, _ = client
    response = http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_chat_returns_id(client, state_module):
    http, _, _ = client
    chat_id = _create_chat(http)
    assert state_module.get_chat(chat_id) is not None


def test_create_chat_requires_api_key(client):
    http, _, _ = client
    response = http.post("/chats", json={"anthropic_api_key": ""})
    assert response.status_code == 400
    response = http.post("/chats", json={"anthropic_api_key": "   "})
    assert response.status_code == 400


def test_create_chat_rejects_missing_body(client):
    http, _, _ = client
    response = http.post("/chats")
    assert response.status_code in (400, 422)


def test_create_chat_response_does_not_contain_api_key(client):
    http, _, _ = client
    response = http.post("/chats", json={"anthropic_api_key": TEST_API_KEY})
    assert response.status_code == 200
    assert TEST_API_KEY not in response.text


def test_api_key_never_appears_in_snapshot_or_events(client, state_module):
    http, _, _ = client
    chat_id = _create_chat(http)

    snapshot = http.get(f"/chats/{chat_id}")
    assert TEST_API_KEY not in snapshot.text

    events = state_module.list_events_after(chat_id)
    for event in events:
        assert TEST_API_KEY not in event.content


def test_send_message_requires_text(client):
    http, _, _ = client
    chat_id = _create_chat(http)
    response = http.post(f"/chats/{chat_id}/messages", json={"text": "  "})
    assert response.status_code == 400


def test_send_message_persists_and_triggers_output(client, state_module):
    http, manager, fake_tmux = client
    chat_id = _create_chat(http)
    session_name = state_module.get_chat(chat_id).tmux_session

    # Simulate Claude output appearing on the pane.
    fake_tmux.write_pane(session_name, "tool says ok\n")

    response = http.post(f"/chats/{chat_id}/messages", json={"text": "hello"})
    assert response.status_code == 200

    assert _wait_for(
        lambda: any(
            e.role == "user" and e.content == "hello"
            for e in state_module.list_events_after(chat_id)
        )
    )
    assert _wait_for(
        lambda: any(
            "tool says ok" in e.content
            for e in state_module.list_events_after(chat_id)
            if e.role == "assistant"
        )
    )


def test_send_message_unknown_chat_returns_404(client):
    http, _, _ = client
    response = http.post("/chats/nope/messages", json={"text": "hi"})
    assert response.status_code == 404


def test_chat_snapshot_returns_events(client, state_module):
    http, _, _ = client
    chat_id = _create_chat(http)
    http.post(f"/chats/{chat_id}/messages", json={"text": "hi"})

    assert _wait_for(
        lambda: any(
            e.role == "user" for e in state_module.list_events_after(chat_id)
        )
    )

    response = http.get(f"/chats/{chat_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat"]["id"] == chat_id
    roles = [e["role"] for e in payload["events"]]
    assert "user" in roles


def test_delete_chat_stops_session(client, state_module):
    http, manager, fake_tmux = client
    chat_id = _create_chat(http)
    session_name = state_module.get_chat(chat_id).tmux_session

    response = http.delete(f"/chats/{chat_id}")
    assert response.status_code == 200

    assert state_module.get_chat(chat_id).status == "stopped"
    assert session_name not in fake_tmux.sessions
    assert not manager.is_active(chat_id)


def test_sse_stream_emits_end_when_chat_stops(client, state_module):
    http, manager, fake_tmux = client
    chat_id = _create_chat(http)

    # Stop chat *before* opening the stream so the endpoint sees inactive.
    manager.stop_chat(chat_id)

    with http.stream("GET", f"/chats/{chat_id}/events") as response:
        assert response.status_code == 200
        collected = []
        for line in response.iter_lines():
            collected.append(line)
            if line.strip() == "event: end":
                break
        assert "event: end" in [l.strip() for l in collected]


def test_sse_stream_delivers_events(client, state_module):
    http, manager, fake_tmux = client
    chat_id = _create_chat(http)
    session_name = state_module.get_chat(chat_id).tmux_session

    # Write pane content then stop to terminate the stream quickly.
    fake_tmux.write_pane(session_name, "streamed-output\n")
    # Wait for the tail thread to convert log into assistant event.
    assert _wait_for(
        lambda: any(
            "streamed-output" in e.content
            for e in state_module.list_events_after(chat_id)
            if e.role == "assistant"
        )
    )
    manager.stop_chat(chat_id)

    data_payloads = []
    with http.stream("GET", f"/chats/{chat_id}/events") as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                data_payloads.append(line[len("data: "):])
            if line.strip() == "event: end":
                break

    assert any(
        "streamed-output" in json.loads(p).get("content", "")
        for p in data_payloads
    )
