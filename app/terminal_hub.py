"""In-memory terminal broadcast hub for active collaboration sessions."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket


@dataclass
class Participant:
    actor_id: str
    label: str
    role: str
    websocket: Optional[WebSocket] = None


class TerminalHub:
    def __init__(self, *, buffer_bytes: int = 256_000) -> None:
        self._buffer_bytes = buffer_bytes
        self._buffers: dict[str, deque[bytes]] = defaultdict(deque)
        self._buffer_sizes: dict[str, int] = defaultdict(int)
        self._subscribers: dict[str, set[asyncio.Queue[bytes]]] = defaultdict(set)
        self._participants: dict[str, dict[str, Participant]] = defaultdict(dict)

    def add_participant(
        self,
        session_name: str,
        *,
        actor_id: str,
        label: str,
        role: str,
        websocket: Optional[WebSocket] = None,
    ) -> None:
        self._participants[session_name][actor_id] = Participant(
            actor_id=actor_id,
            label=label,
            role=role,
            websocket=websocket,
        )

    def remove_participant(self, session_name: str, actor_id: str) -> None:
        self._participants.get(session_name, {}).pop(actor_id, None)

    def participants(self, session_name: str) -> list[dict[str, str]]:
        return [
            {
                "actorId": participant.actor_id,
                "label": participant.label,
                "role": participant.role,
            }
            for participant in self._participants.get(session_name, {}).values()
        ]

    async def close_actor(
        self,
        session_name: str,
        actor_id: str,
        *,
        code: int = 4409,
        reason: str = "control transferred",
    ) -> None:
        participant = self._participants.get(session_name, {}).get(actor_id)
        if not participant or not participant.websocket:
            return
        try:
            await participant.websocket.close(code=code, reason=reason)
        except RuntimeError:
            pass

    def subscribe(self, session_name: str) -> asyncio.Queue[bytes]:
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        for chunk in self._buffers.get(session_name, ()):
            queue.put_nowait(chunk)
        self._subscribers[session_name].add(queue)
        return queue

    def unsubscribe(self, session_name: str, queue: asyncio.Queue[bytes]) -> None:
        self._subscribers.get(session_name, set()).discard(queue)

    async def broadcast(self, session_name: str, chunk: bytes) -> None:
        if not chunk:
            return
        self._append_buffer(session_name, chunk)
        for queue in list(self._subscribers.get(session_name, set())):
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _append_buffer(self, session_name: str, chunk: bytes) -> None:
        buffer = self._buffers[session_name]
        buffer.append(chunk)
        self._buffer_sizes[session_name] += len(chunk)
        while self._buffer_sizes[session_name] > self._buffer_bytes and buffer:
            removed = buffer.popleft()
            self._buffer_sizes[session_name] -= len(removed)
