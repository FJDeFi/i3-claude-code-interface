"""HTTP and WebSocket smoke tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as http:
        yield http


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"xterm" in response.content.lower() or b"terminal" in response.content.lower()


def test_ws_terminal_plain_get_is_upgrade_required(client):
    response = client.get("/ws/terminal")
    assert response.status_code == 426
    assert "WebSocket" in response.json()["detail"]


def test_terminal_websocket_accepts(monkeypatch):
    async def fake_bridge(websocket):
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "message": "stub"}))
        await websocket.close()

    monkeypatch.setattr("app.main.run_terminal_bridge", fake_bridge)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/terminal") as ws:
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "error"
            assert payload["message"] == "stub"
