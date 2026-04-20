from typing import Literal

from pydantic import BaseModel


ChatStatus = Literal["running", "stopped", "failed"]
EventRole = Literal["user", "assistant", "status", "error"]


class Chat(BaseModel):
    id: str
    tmux_session: str
    log_path: str
    status: ChatStatus = "running"


class ChatEvent(BaseModel):
    id: int
    chat_id: str
    role: EventRole
    content: str
    created_at: str


class CreateChatResponse(BaseModel):
    chat_id: str


class CreateChatRequest(BaseModel):
    anthropic_api_key: str


class SendMessageRequest(BaseModel):
    text: str
