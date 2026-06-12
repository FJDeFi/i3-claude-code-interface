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


def test_index_rejected_without_token(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"access denied" in response.content.lower()


def test_firebase_owner_login_sets_web_session_cookie(monkeypatch, client):
    monkeypatch.setenv("CLAUDE_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setattr(
        "app.main.verify_owner_id_token",
        lambda token: {
            "sub": "owner-uid",
            "email": "owner@example.com",
            "name": "Owner",
            "iat": 100,
            "exp": 3700,
        },
    )

    async def fake_create_web_session(**kwargs):
        return "web-session-id", {
            "uid": kwargs["uid"],
            "email": kwargs["email"],
            "displayName": kwargs["display_name"],
        }

    monkeypatch.setattr("app.main.create_web_session", fake_create_web_session)

    response = client.post("/api/auth/firebase", json={"idToken": "firebase-token"})
    assert response.status_code == 200
    assert response.json()["user"]["uid"] == "owner-uid"
    assert response.cookies.get("claude_code_session") == "web-session-id"


def test_index_served_with_firebase_web_session(monkeypatch, client):
    async def fake_validate_web_session(session_id):
        assert session_id == "web-session-id"
        return {
            "role": "owner",
            "status": "active",
            "accessType": "editor",
            "authType": "firebase",
            "uid": "owner-uid",
            "email": "owner@example.com",
        }

    monkeypatch.setattr("app.main.validate_web_session", fake_validate_web_session)
    client.cookies.set("claude_code_session", "web-session-id")

    response = client.get("/")
    assert response.status_code == 200
    assert b"Claude Code" in response.content
    assert b"owner@example.com" in response.content


def test_firebase_login_rejects_non_owner(monkeypatch, client):
    def reject(_token):
        raise PermissionError("This Google account does not own this deployment")

    monkeypatch.setattr("app.main.verify_owner_id_token", reject)
    response = client.post("/api/auth/firebase", json={"idToken": "wrong-user-token"})
    assert response.status_code == 403


def test_index_served_with_valid_token(monkeypatch, client):
    async def fake_validate_token(token):
        return {
            "token": token,
            "role": "owner",
            "status": "active",
            "accessType": "editor",
        }

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)

    response = client.get("/?claudecodeToken=owner-token")
    assert response.status_code == 200
    assert b"Claude Code" in response.content
    assert b"window.__CLAUDE_CODE_SESSION__" in response.content


def test_ws_terminal_plain_get_is_upgrade_required(client):
    response = client.get("/ws/terminal")
    assert response.status_code == 426
    assert "WebSocket" in response.json()["detail"]


def test_tokens_api_requires_privileged_token(client):
    response = client.get("/api/tokens")
    assert response.status_code == 403


def test_tokens_api_list_create_and_revoke(monkeypatch, client):
    async def fake_validate_token(token):
        return {
            "token": token,
            "role": "owner",
            "status": "active",
            "accessType": "editor",
        }

    async def fake_list_tokens():
        return [
            {
                "token": "guest-token",
                "role": "guest",
                "status": "active",
                "accessType": "viewer",
                "createdAt": "2026-05-10T00:00:00Z",
                "ttlSeconds": 3600,
            }
        ]

    async def fake_create_token(**kwargs):
        return {
            "token": "new-token",
            "role": "guest",
            "status": "active",
            "accessType": kwargs["access_type"],
            "ttlSeconds": kwargs["ttl_seconds"],
        }

    async def fake_revoke_token(token):
        return token == "guest-token"

    async def fake_get_token_record(token):
        return {"token": token, "role": "guest"}

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)
    monkeypatch.setattr("app.main.redis_list_tokens", fake_list_tokens)
    monkeypatch.setattr("app.main.create_token", fake_create_token)
    monkeypatch.setattr("app.main.revoke_token", fake_revoke_token)
    monkeypatch.setattr("app.main.get_token_record", fake_get_token_record)

    response = client.get("/api/tokens", headers={"X-Claude-Code-Token": "owner-token"})
    assert response.status_code == 200
    assert response.json()["tokens"][0]["token"] == "guest-token"

    response = client.post(
        "/api/tokens",
        headers={"X-Claude-Code-Token": "owner-token"},
        json={"accessType": "editor", "ttlSeconds": 1800},
    )
    assert response.status_code == 201
    assert response.json()["token"] == "new-token"

    response = client.delete(
        "/api/tokens/guest-token",
        headers={"X-Claude-Code-Token": "owner-token"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


def test_terminal_websocket_accepts(monkeypatch):
    async def fake_bridge(websocket):
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "message": "stub"}))
        await websocket.close()

    async def fake_validate_token(token):
        return {
            "token": token,
            "role": "owner",
            "status": "active",
            "accessType": "editor",
        }

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)
    monkeypatch.setattr("app.main.run_terminal_bridge", fake_bridge)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/terminal?claudecodeToken=owner-token") as ws:
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "error"
            assert payload["message"] == "stub"


def test_terminal_websocket_accepts_firebase_web_session(monkeypatch):
    async def fake_bridge(websocket):
        await websocket.accept()
        assert websocket.state.token_meta["authType"] == "firebase"
        await websocket.send_text(json.dumps({"type": "ready"}))
        await websocket.close()

    async def fake_validate_web_session(session_id):
        assert session_id == "web-session-id"
        return {
            "role": "owner",
            "status": "active",
            "accessType": "editor",
            "authType": "firebase",
            "uid": "owner-uid",
        }

    monkeypatch.setattr("app.main.validate_web_session", fake_validate_web_session)
    monkeypatch.setattr("app.main.run_terminal_bridge", fake_bridge)

    with TestClient(app, cookies={"claude_code_session": "web-session-id"}) as client:
        with client.websocket_connect("/ws/terminal") as ws:
            assert json.loads(ws.receive_text())["type"] == "ready"
