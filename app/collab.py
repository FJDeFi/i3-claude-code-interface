"""Redis-backed collaboration state for Claude Code sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .token import get_redis

COLLAB_PREFIX = "claude:collab:"


def collab_key(session_name: str) -> str:
    return f"{COLLAB_PREFIX}{session_name}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_json_list(value: Optional[str]) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _normalize_state(session_name: str, record: dict[str, str]) -> dict[str, Any]:
    return {
        "session": session_name,
        "masterId": record.get("masterId") or "",
        "masterLabel": record.get("masterLabel") or "Master",
        "controllerId": record.get("controllerId") or "",
        "controllerLabel": record.get("controllerLabel") or "Controller",
        "pendingRequests": _decode_json_list(record.get("pendingRequests")),
        "createdAt": record.get("createdAt") or None,
        "updatedAt": record.get("updatedAt") or None,
    }


async def get_collab_state(session_name: str) -> Optional[dict[str, Any]]:
    redis_client = await get_redis()
    record = await redis_client.hgetall(collab_key(session_name))
    if not record:
        return None
    return _normalize_state(session_name, record)


async def ensure_collab_state(
    session_name: str,
    *,
    master_id: str,
    master_label: str,
) -> dict[str, Any]:
    redis_client = await get_redis()
    key = collab_key(session_name)
    exists = await redis_client.exists(key)
    if not exists:
        now = _utc_now()
        await redis_client.hset(
            key,
            mapping={
                "masterId": master_id,
                "masterLabel": master_label,
                "controllerId": master_id,
                "controllerLabel": master_label,
                "pendingRequests": "[]",
                "createdAt": now,
                "updatedAt": now,
            },
        )
    state = await get_collab_state(session_name)
    if state is None:
        raise RuntimeError("Failed to initialize collaboration state")
    return state


async def request_control(
    session_name: str,
    *,
    actor_id: str,
    actor_label: str,
) -> Optional[dict[str, Any]]:
    state = await get_collab_state(session_name)
    if state is None:
        return None
    if actor_id in {state["masterId"], state["controllerId"]}:
        return state

    pending = [
        item
        for item in state["pendingRequests"]
        if item.get("actorId") != actor_id
    ]
    pending.append(
        {
            "actorId": actor_id,
            "label": actor_label,
            "requestedAt": _utc_now(),
        }
    )
    redis_client = await get_redis()
    await redis_client.hset(
        collab_key(session_name),
        mapping={
            "pendingRequests": json.dumps(pending),
            "updatedAt": _utc_now(),
        },
    )
    return await get_collab_state(session_name)


async def transfer_control(
    session_name: str,
    *,
    master_id: str,
    target_id: str,
    target_label: str,
) -> Optional[tuple[dict[str, Any], str]]:
    state = await get_collab_state(session_name)
    if state is None or state["masterId"] != master_id:
        return None

    old_controller_id = state["controllerId"]
    pending = [
        item
        for item in state["pendingRequests"]
        if item.get("actorId") != target_id
    ]
    redis_client = await get_redis()
    await redis_client.hset(
        collab_key(session_name),
        mapping={
            "controllerId": target_id,
            "controllerLabel": target_label,
            "pendingRequests": json.dumps(pending),
            "updatedAt": _utc_now(),
        },
    )
    updated = await get_collab_state(session_name)
    if updated is None:
        return None
    return updated, old_controller_id


async def approve_control_request(
    session_name: str,
    *,
    master_id: str,
    requester_id: str,
) -> Optional[tuple[dict[str, Any], str]]:
    state = await get_collab_state(session_name)
    if state is None or state["masterId"] != master_id:
        return None

    request = next(
        (
            item
            for item in state["pendingRequests"]
            if item.get("actorId") == requester_id
        ),
        None,
    )
    if request is None:
        return None
    return await transfer_control(
        session_name,
        master_id=master_id,
        target_id=requester_id,
        target_label=str(request.get("label") or "Controller"),
    )
