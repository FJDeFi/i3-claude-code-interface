from .claude import run_claude
from .prompt import SYSTEM_PROMPT
from .tools import execute_tool

TOOLS_SCHEMA = [
    {
        "name": "run_shell",
        "description": "Run a shell command and return stdout/stderr",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    }
]


def agent_loop(user_prompt: str, max_steps: int = 10) -> str:
    messages = [{"role": "user", "content": user_prompt}]

    for _ in range(max_steps):
        response = run_claude(
            messages=messages,
            tools_schema=TOOLS_SCHEMA,
            system_prompt=SYSTEM_PROMPT,
        )

        if response["type"] == "text":
            return response["text"]

        if response["type"] == "tool_call":
            tool_name = response["name"]
            tool_input = response["input"]
            result = execute_tool(tool_name, tool_input)

            messages.append({
                "role": "assistant",
                "content": response["assistant_content"],
            })
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": response["id"],
                        "content": result,
                    }
                ],
            })

    return "Max steps reached"
