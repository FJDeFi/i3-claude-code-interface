import os
from typing import Any

from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "ANTHROPIC_FALLBACK_MODELS",
        "claude-sonnet-4-20250514,claude-3-7-sonnet-20250219,claude-3-5-haiku-latest,claude-3-haiku-20240307",
    ).split(",")
    if model.strip()
]


def _is_model_not_found_error(exc: Exception) -> bool:
    message = str(exc)
    return "not_found_error" in message and "model:" in message


def _candidate_models() -> list[str]:
    candidates = [MODEL, *FALLBACK_MODELS]
    unique_candidates: list[str] = []
    seen: set[str] = set()
    for model in candidates:
        if model not in seen:
            seen.add(model)
            unique_candidates.append(model)
    return unique_candidates


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
    last_error: Exception | None = None
    response = None

    for model in _candidate_models():
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
                tools=tools_schema,
            )
            break
        except Exception as exc:
            last_error = exc
            if _is_model_not_found_error(exc):
                continue
            raise

    if response is None:
        raise RuntimeError(
            f"No available Anthropic model found from candidates: {_candidate_models()}"
        ) from last_error

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
