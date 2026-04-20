"""SQLite-backed storage for chats and chat events.

The schema has two tables:

* ``chats`` — one row per chat, tracking the tmux session name and status.
* ``chat_events`` — append-only log of user input, assistant output chunks,
  status transitions, and errors. SSE streams replay rows with id greater
  than the subscriber's cursor, so reconnecting clients never miss output.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from .models import Chat, ChatEvent, ChatStatus, EventRole


DB_PATH = os.getenv(
    "CHAT_DB_PATH", str(Path(__file__).resolve().parent / "chats.db")
)


_write_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    with closing(_get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                tmux_session TEXT NOT NULL,
                log_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                anthropic_api_key TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(chat_id) REFERENCES chats(id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_events_chat_id
                ON chat_events(chat_id, id);
            """
        )

        # Backfill anthropic_api_key column for pre-existing databases.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chats)")}
        if "anthropic_api_key" not in columns:
            conn.execute("ALTER TABLE chats ADD COLUMN anthropic_api_key TEXT")


init_db()


# --------------------------------------------------------------------- chats


def insert_chat(
    chat_id: str,
    tmux_session: str,
    log_path: str,
    anthropic_api_key: Optional[str] = None,
) -> Chat:
    with _write_lock, closing(_get_conn()) as conn:
        conn.execute(
            "INSERT INTO chats (id, tmux_session, log_path, status, anthropic_api_key)"
            " VALUES (?, ?, ?, 'running', ?)",
            (chat_id, tmux_session, log_path, anthropic_api_key),
        )
    return Chat(
        id=chat_id,
        tmux_session=tmux_session,
        log_path=log_path,
        status="running",
    )


def get_chat_api_key(chat_id: str) -> Optional[str]:
    """Internal accessor for a chat's stored API key. NEVER expose via HTTP."""
    with closing(_get_conn()) as conn:
        row = conn.execute(
            "SELECT anthropic_api_key FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
    if not row:
        return None
    return row["anthropic_api_key"]


def clear_chat_api_key(chat_id: str) -> None:
    with _write_lock, closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE chats SET anthropic_api_key = NULL WHERE id = ?",
            (chat_id,),
        )


def get_chat(chat_id: str) -> Optional[Chat]:
    with closing(_get_conn()) as conn:
        row = conn.execute(
            "SELECT id, tmux_session, log_path, status FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    if not row:
        return None
    return Chat(
        id=row["id"],
        tmux_session=row["tmux_session"],
        log_path=row["log_path"],
        status=row["status"],
    )


def update_chat_status(chat_id: str, status: ChatStatus) -> None:
    with _write_lock, closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE chats SET status = ? WHERE id = ?",
            (status, chat_id),
        )


def list_chats() -> List[Chat]:
    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, tmux_session, log_path, status FROM chats"
            " ORDER BY created_at DESC"
        ).fetchall()
    return [
        Chat(
            id=row["id"],
            tmux_session=row["tmux_session"],
            log_path=row["log_path"],
            status=row["status"],
        )
        for row in rows
    ]


# -------------------------------------------------------------------- events


def append_chat_event(chat_id: str, role: EventRole, content: str) -> ChatEvent:
    with _write_lock, closing(_get_conn()) as conn:
        cursor = conn.execute(
            "INSERT INTO chat_events (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        event_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, chat_id, role, content, created_at"
            " FROM chat_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    return ChatEvent(
        id=row["id"],
        chat_id=row["chat_id"],
        role=row["role"],
        content=row["content"],
        created_at=str(row["created_at"]),
    )


def list_events_after(chat_id: str, after_id: int = 0, limit: int = 500) -> List[ChatEvent]:
    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, chat_id, role, content, created_at FROM chat_events"
            " WHERE chat_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (chat_id, after_id, limit),
        ).fetchall()
    return [
        ChatEvent(
            id=row["id"],
            chat_id=row["chat_id"],
            role=row["role"],
            content=row["content"],
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]
