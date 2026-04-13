import os
from typing import Any

from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")


def _serialize_content_block(block: Any) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return {"type": block.type}


def run_claude(
    messages: list[dict[str, Any]],
    tools_schema: list[dict[str, Any]],
    system_prompt: str,
) -> dict[str, Any]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        tools=tools_schema,
    )

    content_blocks = [_serialize_content_block(block) for block in response.content]

    for block in content_blocks:
        if block["type"] == "tool_use":
            return {
                "type": "tool_call",
                "id": block["id"],
                "name": block["name"],
                "input": block["input"],
                "assistant_content": content_blocks,
            }

    text = "".join(
        block["text"] for block in content_blocks if block["type"] == "text"
    ).strip()
    return {"type": "text", "text": text or "No response text returned."}
