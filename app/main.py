"""FastAPI entrypoint for the tmux-backed Claude Code bridge."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .chat_session import ChatManager
from .models import CreateChatRequest, SendMessageRequest
from .state import get_chat, list_events_after


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    app.state.chat_manager.shutdown()


app = FastAPI(title="Claude Code tmux bridge", lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.state.chat_manager = ChatManager()


def _manager(req_app: FastAPI = app) -> ChatManager:
    return req_app.state.chat_manager


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chats")
def create_chat(body: CreateChatRequest) -> dict:
    # #region agent log
    from .agent_debug import agent_log

    key = (body.anthropic_api_key or "").strip()
    agent_log(
        "main.py:create_chat",
        "entry",
        {
            "key_len": len(key),
            "has_newline": "\n" in key,
            "has_cr": "\r" in key,
        },
        "H5",
    )
    # #endregion
    if not key:
        raise HTTPException(
            status_code=400, detail="anthropic_api_key must not be empty"
        )
    try:
        chat_id = _manager().create_chat(anthropic_api_key=key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # #region agent log
        agent_log(
            "main.py:create_chat",
            "exception_before_500",
            {
                "exc_type": type(exc).__name__,
                "exc_msg": str(exc)[:800],
            },
            "H1-H4",
        )
        # #endregion
        raise
    # #region agent log
    agent_log(
        "main.py:create_chat",
        "success",
        {"chat_id": chat_id},
        "H0",
    )
    # #endregion
    return {"chat_id": chat_id}


@app.post("/chats/{chat_id}/messages")
def send_message(chat_id: str, body: SendMessageRequest) -> dict:
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        _manager().send_message(chat_id, text)
    except KeyError:
        raise HTTPException(status_code=404, detail="chat not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "accepted"}


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    if get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    _manager().stop_chat(chat_id)
    return {"status": "stopped"}


@app.get("/chats/{chat_id}")
def chat_snapshot(chat_id: str) -> dict:
    chat = get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    events = list_events_after(chat_id, after_id=0, limit=10_000)
    return {
        "chat": chat.model_dump(),
        "events": [event.model_dump() for event in events],
    }


@app.get("/chats/{chat_id}/events")
async def chat_events(chat_id: str, after_id: int = 0) -> StreamingResponse:
    """Server-Sent Events stream of chat events newer than ``after_id``."""

    if get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")

    manager = _manager()

    async def event_stream() -> AsyncIterator[bytes]:
        cursor = after_id
        # Initial replay so reconnecting clients always see full history.
        while True:
            events = await asyncio.to_thread(
                list_events_after, chat_id, cursor, 200
            )
            for event in events:
                cursor = event.id
                payload = json.dumps(event.model_dump())
                yield f"id: {event.id}\nevent: {event.role}\ndata: {payload}\n\n".encode()

            if not manager.is_active(chat_id):
                yield b"event: end\ndata: {}\n\n"
                return

            await asyncio.sleep(0.4)

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
