"""Temporary NDJSON debug logger for session c9f1e0 — remove after verified fix."""

from __future__ import annotations

import json
import time

_LOG_PATH = "/Users/chenyiyu/code/i3/i3-claude-code-interface/.cursor/debug-c9f1e0.log"
_SESSION_ID = "c9f1e0"


def agent_log(
    location: str, message: str, data: dict, hypothesis_id: str
) -> None:
    try:
        line = json.dumps(
            {
                "sessionId": _SESSION_ID,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
                "hypothesisId": hypothesis_id,
            },
            ensure_ascii=False,
        )
        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass
