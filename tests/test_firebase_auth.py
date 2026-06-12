from __future__ import annotations

import pytest

from app import firebase_auth


def test_verify_owner_id_token_accepts_configured_owner(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "firebase-project")
    monkeypatch.setenv("CLAUDE_OWNER_UID", "owner-uid")
    monkeypatch.setattr(
        firebase_auth.id_token,
        "verify_firebase_token",
        lambda token, request, audience: {
            "sub": "owner-uid",
            "email": "owner@example.com",
        },
    )

    claims = firebase_auth.verify_owner_id_token("valid-token")
    assert claims["sub"] == "owner-uid"


def test_verify_owner_id_token_rejects_other_user(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "firebase-project")
    monkeypatch.setenv("CLAUDE_OWNER_UID", "owner-uid")
    monkeypatch.setattr(
        firebase_auth.id_token,
        "verify_firebase_token",
        lambda token, request, audience: {"sub": "other-uid"},
    )

    with pytest.raises(PermissionError):
        firebase_auth.verify_owner_id_token("other-user-token")
