"""In-memory terminal broadcast hub for active collaboration sessions."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional, Union

from fastapi import WebSocket


@dataclass
class Participant:
    actor_id: str
    label: str
    role: str
    websocket: Optional[WebSocket] = None


@dataclass(frozen=True)
class TerminalSize:
    cols: int
    rows: int


TerminalEvent = Union[bytes, dict[str, object]]


class TerminalHub:
    def __init__(self, *, buffer_bytes: int = 256_000) -> None:
        self._buffer_bytes = buffer_bytes
        self._buffers: dict[str, deque[bytes]] = defaultdict(deque)
        self._buffer_sizes: dict[str, int] = defaultdict(int)
        self._subscribers: dict[str, set[asyncio.Queue[TerminalEvent]]] = defaultdict(set)
        self._participants: dict[str, dict[str, Participant]] = defaultdict(dict)
        self._sizes: dict[str, TerminalSize] = {}

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

    def terminal_size(self, session_name: str) -> Optional[dict[str, int]]:
        size = self._sizes.get(session_name)
        if not size:
            return None
        return {"cols": size.cols, "rows": size.rows}

    async def set_terminal_size(self, session_name: str, cols: int, rows: int) -> None:
        size = TerminalSize(cols=cols, rows=rows)
        if self._sizes.get(session_name) == size:
            return
        self._sizes[session_name] = size
        await self._broadcast_event(
            session_name,
            {"type": "terminal-size", "cols": cols, "rows": rows},
        )

    def subscribe(self, session_name: str) -> asyncio.Queue[TerminalEvent]:
        queue: asyncio.Queue[TerminalEvent] = asyncio.Queue(maxsize=250)
        size = self.terminal_size(session_name)
        if size:
            queue.put_nowait({"type": "terminal-size", **size})
        for chunk in self._buffers.get(session_name, ()):
            queue.put_nowait(chunk)
        self._subscribers[session_name].add(queue)
        return queue

    def unsubscribe(self, session_name: str, queue: asyncio.Queue[TerminalEvent]) -> None:
        self._subscribers.get(session_name, set()).discard(queue)

    async def broadcast(self, session_name: str, chunk: bytes) -> None:
        if not chunk:
            return
        self._append_buffer(session_name, chunk)
        await self._broadcast_event(session_name, chunk)

    async def _broadcast_event(self, session_name: str, event: TerminalEvent) -> None:
        for queue in list(self._subscribers.get(session_name, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def _append_buffer(self, session_name: str, chunk: bytes) -> None:
        buffer = self._buffers[session_name]
        buffer.append(chunk)
        self._buffer_sizes[session_name] += len(chunk)
        while self._buffer_sizes[session_name] > self._buffer_bytes and buffer:
            removed = buffer.popleft()
            self._buffer_sizes[session_name] -= len(removed)
