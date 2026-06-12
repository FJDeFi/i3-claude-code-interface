"""Firebase ID token verification for deployment-owner authentication."""

from __future__ import annotations

import os
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


def firebase_project_id() -> str:
    return os.getenv("FIREBASE_PROJECT_ID", "").strip()


def deployment_owner_uid() -> str:
    return os.getenv("CLAUDE_OWNER_UID", "").strip()


def verify_owner_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and require the configured deployment owner."""
    project_id = firebase_project_id()
    owner_uid = deployment_owner_uid()
    if not project_id:
        raise ValueError("FIREBASE_PROJECT_ID is not configured")
    if not owner_uid:
        raise ValueError("CLAUDE_OWNER_UID is not configured")
    if not token:
        raise ValueError("Firebase ID token is required")

    claims = id_token.verify_firebase_token(
        token,
        google_requests.Request(),
        audience=project_id,
    )
    if not claims:
        raise ValueError("Invalid Firebase ID token")

    uid = str(claims.get("sub") or claims.get("user_id") or "").strip()
    if uid != owner_uid:
        raise PermissionError("This Google account does not own this deployment")
    return claims
