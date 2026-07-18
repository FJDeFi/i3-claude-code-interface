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


def test_preview_requires_valid_session(client):
    response = client.get("/preview/5173/")
    assert response.status_code == 403


def test_preview_rejects_unsafe_port(monkeypatch, client):
    async def fake_validate_token(token):
        return {
            "token": token,
            "role": "owner",
            "status": "active",
            "accessType": "editor",
        }

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)
    response = client.get("/preview/80/", headers={"X-Claude-Code-Token": "owner-token"})
    assert response.status_code == 400
    assert "port" in response.json()["detail"].lower()


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


def test_create_claudecode_session_hides_tmux_status(monkeypatch, client):
    commands = []

    async def fake_require_privileged_session(request):
        return {
            "token": "owner-token",
            "role": "owner",
            "status": "active",
            "accessType": "editor",
        }

    async def fake_ensure_collab_state(*args, **kwargs):
        return None

    def fake_run_cmd(cmd):
        commands.append(cmd)
        return 0, "", ""

    monkeypatch.setattr("app.main._require_privileged_session", fake_require_privileged_session)
    monkeypatch.setattr("app.main.ensure_collab_state", fake_ensure_collab_state)
    monkeypatch.setattr("app.main._run_cmd", fake_run_cmd)

    response = client.post("/api/claudecode/sessions", json={"name": "demo"})

    assert response.status_code == 200
    assert commands == [
        "tmux new -d -s demo",
        "tmux set-option -t demo status off",
    ]


def test_collab_api_status_request_and_transfer(monkeypatch, client):
    collab_state = {
        "session": "demo",
        "masterId": "token:owner-token",
        "masterLabel": "owner",
        "controllerId": "token:owner-token",
        "controllerLabel": "owner",
        "pendingRequests": [],
    }

    async def fake_validate_token(token):
        if token == "owner-token":
            return {
                "token": token,
                "role": "owner",
                "status": "active",
                "accessType": "editor",
                "session": "*",
            }
        return {
            "token": token,
            "role": "guest",
            "status": "active",
            "accessType": "viewer",
            "session": "demo",
        }

    async def fake_get_collab_state(name):
        return {**collab_state, "session": name}

    async def fake_ensure(tmux_session, session):
        return await fake_get_collab_state(tmux_session)

    async def fake_request_control(name, actor_id, actor_label):
        collab_state["pendingRequests"] = [{"actorId": actor_id, "label": actor_label}]
        return await fake_get_collab_state(name)

    async def fake_transfer(name, master_id, target_id, target_label):
        collab_state["controllerId"] = target_id
        collab_state["controllerLabel"] = target_label
        collab_state["pendingRequests"] = []
        return (
            await fake_get_collab_state(name),
            "token:owner-token",
        )

    async def fake_approve(name, master_id, requester_id):
        return await fake_transfer(name, master_id, requester_id, "guest")

    async def fake_close_actor(*args, **kwargs):
        return None

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)
    monkeypatch.setattr("app.main.get_collab_state", fake_get_collab_state)
    monkeypatch.setattr("app.main._ensure_collab_for_privileged", fake_ensure)
    monkeypatch.setattr("app.main.request_control", fake_request_control)
    monkeypatch.setattr("app.main.transfer_control", fake_transfer)
    monkeypatch.setattr("app.main.approve_control_request", fake_approve)
    monkeypatch.setattr("app.main.terminal_hub.close_actor", fake_close_actor)

    response = client.get(
        "/api/claudecode/sessions/demo/collab",
        headers={"X-Claude-Code-Token": "owner-token"},
    )
    assert response.status_code == 200
    assert response.json()["isMaster"] is True
    assert response.json()["isController"] is True

    response = client.post(
        "/api/claudecode/sessions/demo/request-control",
        headers={"X-Claude-Code-Token": "guest-token"},
    )
    assert response.status_code == 200
    assert response.json()["pendingRequests"][0]["actorId"] == "token:guest-token"

    response = client.post(
        "/api/claudecode/sessions/demo/approve-control",
        headers={"X-Claude-Code-Token": "owner-token"},
        json={"actorId": "token:guest-token"},
    )
    assert response.status_code == 200
    assert response.json()["controllerId"] == "token:guest-token"

    response = client.post(
        "/api/claudecode/sessions/demo/transfer-control",
        headers={"X-Claude-Code-Token": "owner-token"},
        json={"actorId": "token:guest-token", "label": "guest"},
    )
    assert response.status_code == 200
    assert response.json()["controllerId"] == "token:guest-token"


def test_terminal_websocket_accepts(monkeypatch):
    async def fake_bridge(websocket, **kwargs):
        assert kwargs["start"][1] == "demo"
        assert kwargs["accept"] is False
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
    async def fake_ensure_collab(tmux_session, session):
        return {
            "masterId": "token:owner-token",
            "controllerId": "token:owner-token",
        }

    async def fake_collab_payload(tmux_session, session):
        return {
            "session": tmux_session,
            "actorId": "token:owner-token",
            "isMaster": True,
            "isController": True,
            "collabRole": "master-controller",
        }

    monkeypatch.setattr("app.main._ensure_collab_for_privileged", fake_ensure_collab)
    monkeypatch.setattr("app.main._collab_payload", fake_collab_payload)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/terminal?claudecodeToken=owner-token") as ws:
            ws.send_text(json.dumps({"type": "start", "session": "demo"}))
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "collab"
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "error"
            assert payload["message"] == "stub"


def test_terminal_websocket_accepts_firebase_web_session(monkeypatch):
    async def fake_bridge(websocket, **kwargs):
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
    async def fake_ensure_collab(tmux_session, session):
        return {
            "masterId": "web:web-session-id",
            "controllerId": "web:web-session-id",
        }

    async def fake_collab_payload(tmux_session, session):
        return {
            "session": tmux_session,
            "actorId": "web:web-session-id",
            "isMaster": True,
            "isController": True,
            "collabRole": "master-controller",
        }

    monkeypatch.setattr("app.main._ensure_collab_for_privileged", fake_ensure_collab)
    monkeypatch.setattr("app.main._collab_payload", fake_collab_payload)

    with TestClient(app, cookies={"claude_code_session": "web-session-id"}) as client:
        with client.websocket_connect("/ws/terminal") as ws:
            ws.send_text(json.dumps({"type": "start", "session": "demo"}))
            assert json.loads(ws.receive_text())["type"] == "collab"
            assert json.loads(ws.receive_text())["type"] == "ready"


def test_terminal_websocket_guest_attaches_read_only(monkeypatch):
    bridge_calls = []

    async def fake_bridge(websocket, **kwargs):
        bridge_calls.append(kwargs)
        await websocket.send_text(json.dumps({"type": "ready"}))
        await websocket.close()

    async def fake_validate_token(token):
        return {
            "token": token,
            "role": "guest",
            "status": "active",
            "accessType": "viewer",
            "session": "demo",
        }

    async def fake_ensure_collab(tmux_session, session):
        return {
            "masterId": "token:owner-token",
            "controllerId": "token:owner-token",
        }

    async def fake_collab_payload(tmux_session, session):
        return {
            "session": tmux_session,
            "actorId": "token:guest-token",
            "isMaster": False,
            "isController": False,
            "collabRole": "viewer",
        }

    monkeypatch.setattr("app.main.validate_token", fake_validate_token)
    monkeypatch.setattr("app.main.run_terminal_bridge", fake_bridge)
    monkeypatch.setattr("app.main._ensure_collab_for_privileged", fake_ensure_collab)
    monkeypatch.setattr("app.main._collab_payload", fake_collab_payload)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/terminal?claudecodeToken=guest-token") as ws:
            ws.send_text(json.dumps({"type": "start", "session": "demo"}))
            assert json.loads(ws.receive_text())["type"] == "collab"
            assert json.loads(ws.receive_text())["type"] == "ready"

    assert bridge_calls
    assert bridge_calls[0]["read_only"] is True
    assert bridge_calls[0]["accept"] is False
