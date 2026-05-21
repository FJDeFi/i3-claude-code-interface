from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("CLAUDE_CODE_REDIS_URL", "redis://127.0.0.1:6379")
TOKEN_PREFIX = "claude:token:"
TOKEN_INDEX_KEY = "claude:tokens:index"

_redis: Optional[aioredis.Redis] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def token_key(token: str) -> str:
    return f"{TOKEN_PREFIX}{token}"


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _normalize_record(token: str, record: dict[str, str]) -> dict[str, Any]:
    ttl_seconds_raw = record.get("ttlSeconds")
    ttl_seconds: Optional[int]
    try:
        ttl_seconds = int(ttl_seconds_raw) if ttl_seconds_raw not in (None, "") else None
    except ValueError:
        ttl_seconds = None
    return {
        "token": token,
        "role": record.get("role") or "guest",
        "status": record.get("status") or "active",
        "accessType": record.get("accessType") or "viewer",
        "session": record.get("session") or "*",
        "createdAt": record.get("createdAt"),
        "createdBy": record.get("createdBy") or None,
        "deploymentId": record.get("deploymentId") or None,
        "ownerDeploymentId": record.get("ownerDeploymentId") or None,
        "ttlSeconds": ttl_seconds,
        "expiresAt": record.get("expiresAt") or None,
    }


async def get_token_record(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None
    redis_client = await get_redis()
    record = await redis_client.hgetall(token_key(token))
    if not record:
        return None
    return _normalize_record(token, record)


async def validate_token(token: str) -> Optional[dict[str, Any]]:
    """Return token metadata if present and active, else None."""
    record = await get_token_record(token)
    if not record:
        return None
    if record.get("status") != "active":
        return None
    return record


async def create_token(
    *,
    access_type: str = "viewer",
    ttl_seconds: Optional[int] = None,
    role: str = "guest",
    created_by: Optional[str] = None,
    deployment_id: Optional[str] = None,
    session: Optional[str] = None,
) -> dict[str, Any]:
    token = secrets.token_hex(32)
    await store_token(
        token,
        access_type=access_type,
        ttl_seconds=ttl_seconds,
        role=role,
        created_by=created_by,
        deployment_id=deployment_id,
        session=session,
    )
    return {"token": token, **(await get_token_record(token) or {})}


async def store_token(
    token: str,
    *,
    access_type: str = "viewer",
    ttl_seconds: Optional[int] = None,
    role: str = "guest",
    created_by: Optional[str] = None,
    deployment_id: Optional[str] = None,
    session: Optional[str] = None,
    status: str = "active",
    owner_deployment_id: Optional[str] = None,
) -> dict[str, Any]:
    redis_client = await get_redis()
    record: dict[str, str] = {
        "role": role,
        "status": status,
        "accessType": access_type,
        "createdAt": _utc_now(),
    }
    # session: either '*' for all sessions or comma-separated session ids
    if session is None:
        record["session"] = "*"
    else:
        record["session"] = session
    if created_by:
        record["createdBy"] = created_by
    if deployment_id:
        record["deploymentId"] = deployment_id
    if owner_deployment_id:
        record["ownerDeploymentId"] = owner_deployment_id

    if ttl_seconds is not None and ttl_seconds > 0:
        record["ttlSeconds"] = str(int(ttl_seconds))
        record["expiresAt"] = (datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))).isoformat().replace("+00:00", "Z")

    await redis_client.hset(token_key(token), mapping=record)
    await redis_client.sadd(TOKEN_INDEX_KEY, token)
    if ttl_seconds is not None and ttl_seconds > 0:
        await redis_client.expire(token_key(token), int(ttl_seconds))
    return {"token": token, **_normalize_record(token, record)}


async def list_tokens() -> list[dict[str, Any]]:
    redis_client = await get_redis()
    tokens = sorted(await redis_client.smembers(TOKEN_INDEX_KEY))
    results: list[dict[str, Any]] = []
    for token in tokens:
        record = await get_token_record(token)
        if record:
            results.append(record)
    return results


async def revoke_token(token: str) -> bool:
    if not token:
        return False
    redis_client = await get_redis()
    key = token_key(token)
    exists = await redis_client.exists(key)
    if not exists:
        return False
    record = await redis_client.hgetall(key)
    if record.get("role") == "owner":
        return False
    await redis_client.hset(key, mapping={"status": "revoked"})
    await redis_client.sadd(TOKEN_INDEX_KEY, token)
    return True


async def create_owner_token(token: str, deployment_id: Optional[str] = None) -> dict[str, Any]:
    return await store_token(
        token,
        access_type="editor",
        role="owner",
        deployment_id=deployment_id,
        owner_deployment_id=deployment_id,
        status="active",
        session="*",
    )
