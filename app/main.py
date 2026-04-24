"""FastAPI entrypoint: static UI + WebSocket PTY bridge over SSH."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ssh_terminal import run_terminal_bridge


app = FastAPI(title="Claude Code SSH terminal bridge")
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    await run_terminal_bridge(websocket)
