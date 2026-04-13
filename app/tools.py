import subprocess


def run_shell(command: str) -> str:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        return str(exc)

    output = (completed.stdout or "") + (completed.stderr or "")
    return output.strip() or "(no output)"


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file_obj:
            return file_obj.read()
    except Exception as exc:
        return str(exc)


TOOLS = {
    "run_shell": run_shell,
    "read_file": read_file,
}


def execute_tool(name: str, args: dict) -> str:
    if name not in TOOLS:
        return f"Unknown tool: {name}"

    try:
        return TOOLS[name](**args)
    except Exception as exc:
        return str(exc)
