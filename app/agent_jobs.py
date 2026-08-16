"""Single-VM Claude Code job queue backed by job directories and tmux."""

from __future__ import annotations

import asyncio
import json
import os
import pwd
import shlex
import shutil
import subprocess
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TERMINAL_STATES = {"completed", "failed", "cancelled"}
SYSTEM_PROMPT = """You are an unattended data-improvement worker running inside one isolated job directory.
Read the user's instruction and every relevant file under input/. Work only inside this job directory.
Write every deliverable under output/. Always write output/summary.md describing what you changed.
Do not ask follow-up questions. If information is missing, make a reasonable assumption and record it in output/summary.md.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AgentJobManager:
    def __init__(
        self,
        root: Path | None = None,
        *,
        job_user: str | None = None,
        claude_cmd: str | None = None,
        poll_seconds: float = 1.0,
        timeout_seconds: int | None = None,
    ) -> None:
        self.root = Path(root or os.getenv("AGENT_JOBS_DIR", "/var/lib/i3-agent-jobs"))
        self.job_user = (job_user if job_user is not None else os.getenv("AGENT_JOBS_USER", os.getenv("SSH_USER", ""))).strip()
        self.claude_cmd = (claude_cmd or os.getenv("CLAUDE_CODE_CMD", "claude")).strip() or "claude"
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds or int(os.getenv("AGENT_JOB_TIMEOUT_SECONDS", "3600"))
        self._worker_task: asyncio.Task[None] | None = None
        self._worker_lock = asyncio.Lock()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        # A service restart destroys the in-process monitor. Requeue any job
        # which was running so the single worker can safely start it again.
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            record = self.get_job(path.name)
            if record and record.get("status") == "running":
                record["status"] = "queued"
                record["startedAt"] = None
                record["error"] = "Requeued after service restart"
                self._write_record(path.name, record)

    def create_job(self, name: str, instruction: str, files: Iterable[tuple[str, bytes]]) -> dict[str, Any]:
        self.initialize()
        clean_name = name.strip()[:120]
        clean_instruction = instruction.strip()
        if not clean_name:
            raise ValueError("Job name is required")
        if not clean_instruction:
            raise ValueError("Instruction is required")
        if len(clean_instruction) > 50_000:
            raise ValueError("Instruction is too long")

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.root / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()

        saved_names: list[str] = []
        for raw_name, content in files:
            filename = Path(raw_name or "").name
            if not filename or filename in {".", ".."}:
                raise ValueError("Every uploaded file must have a valid filename")
            if filename in saved_names:
                raise ValueError(f"Duplicate filename: {filename}")
            (input_dir / filename).write_bytes(content)
            saved_names.append(filename)

        (job_dir / "instruction.txt").write_text(clean_instruction + "\n", encoding="utf-8")
        (job_dir / "system-prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
        record: dict[str, Any] = {
            "id": job_id,
            "name": clean_name,
            "status": "queued",
            "createdAt": _now(),
            "startedAt": None,
            "finishedAt": None,
            "files": saved_names,
            "error": None,
            "tmuxSession": f"i3-job-{job_id}",
        }
        self._write_record(job_id, record)
        self._write_runner(job_id)
        self._grant_job_user_access(job_dir)
        return record

    def list_jobs(self) -> list[dict[str, Any]]:
        self.initialize()
        jobs = [record for path in self.root.iterdir() if path.is_dir() if (record := self.get_job(path.name))]
        return sorted(jobs, key=lambda item: str(item.get("createdAt") or ""), reverse=True)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if not self._valid_id(job_id):
            return None
        try:
            return json.loads((self.root / job_id / "job.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def log_text(self, job_id: str, limit: int = 100_000) -> str:
        if not self.get_job(job_id):
            raise FileNotFoundError(job_id)
        try:
            data = (self.root / job_id / "claude.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return data[-max(1, min(limit, 500_000)):]

    def result_archive(self, job_id: str) -> Path:
        record = self.get_job(job_id)
        if not record or record.get("status") != "completed":
            raise FileNotFoundError(job_id)
        job_dir = self.root / job_id
        output_dir = job_dir / "output"
        archive = job_dir / "result.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(output_dir.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    bundle.write(path, path.relative_to(output_dir))
        return archive

    async def cancel(self, job_id: str) -> dict[str, Any] | None:
        record = self.get_job(job_id)
        if not record or record.get("status") in TERMINAL_STATES:
            return record
        record["status"] = "cancelled"
        record["finishedAt"] = _now()
        self._write_record(job_id, record)
        await self._tmux("kill-session", "-t", str(record["tmuxSession"]), check=False)
        return record

    def ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        async with self._worker_lock:
            while True:
                queued = [job for job in reversed(self.list_jobs()) if job.get("status") == "queued"]
                if not queued:
                    return
                await self._run_job(queued[0])

    async def _run_job(self, record: dict[str, Any]) -> None:
        job_id = str(record["id"])
        latest = self.get_job(job_id)
        if not latest or latest.get("status") != "queued":
            return
        record = latest
        job_dir = self.root / job_id
        session = str(record["tmuxSession"])
        record["status"] = "running"
        record["startedAt"] = _now()
        self._write_record(job_id, record)

        await self._tmux("kill-session", "-t", session, check=False)
        created = await self._tmux("new-session", "-d", "-s", session, "-c", str(job_dir), check=False)
        if created.returncode != 0:
            self._finish(record, "failed", created.stderr.strip() or "Could not create tmux session")
            return
        injected = await self._tmux("send-keys", "-t", session, "bash runner.sh", "Enter", check=False)
        if injected.returncode != 0:
            self._finish(record, "failed", injected.stderr.strip() or "Could not inject the job into tmux")
            return

        deadline = time.monotonic() + self.timeout_seconds
        exit_file = job_dir / "exit-code"
        while time.monotonic() < deadline:
            latest = self.get_job(job_id)
            if not latest or latest.get("status") == "cancelled":
                return
            if exit_file.exists():
                try:
                    exit_code = int(exit_file.read_text().strip())
                except (OSError, ValueError):
                    exit_code = 1
                if exit_code == 0 and any(path.is_file() for path in (job_dir / "output").rglob("*")):
                    self._finish(record, "completed", None)
                else:
                    self._finish(record, "failed", f"Claude exited with code {exit_code}; inspect the job log")
                await self._tmux("kill-session", "-t", session, check=False)
                return
            await asyncio.sleep(self.poll_seconds)

        await self._tmux("kill-session", "-t", session, check=False)
        self._finish(record, "failed", f"Job exceeded the {self.timeout_seconds}-second timeout")

    def _finish(self, record: dict[str, Any], status: str, error: str | None) -> None:
        record["status"] = status
        record["error"] = error
        record["finishedAt"] = _now()
        self._write_record(str(record["id"]), record)

    async def _tmux(self, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
        command = self._user_prefix() + ["tmux", *args]
        return await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, check=check)

    def _user_prefix(self) -> list[str]:
        current = pwd.getpwuid(os.geteuid()).pw_name
        if not self.job_user or self.job_user == current:
            return []
        if os.geteuid() != 0:
            raise RuntimeError(f"Cannot run agent jobs as {self.job_user} from non-root service user {current}")
        account = pwd.getpwnam(self.job_user)
        return [
            "runuser", "-u", self.job_user, "--", "env",
            f"HOME={account.pw_dir}", f"USER={self.job_user}", f"LOGNAME={self.job_user}",
        ]

    def _write_runner(self, job_id: str) -> None:
        job_dir = self.root / job_id
        claude = shlex.quote(self.claude_cmd)
        runner = f"""#!/bin/bash
set -u
set -o pipefail
export PATH="$HOME/.local/bin:$PATH"
prompt=$(cat instruction.txt)
system_prompt=$(cat system-prompt.txt)
{claude} -p --dangerously-skip-permissions --output-format text --append-system-prompt "$system_prompt" "$prompt" 2>&1 | tee claude.log output/response.txt
rc=${{PIPESTATUS[0]}}
printf '%s\\n' "$rc" > exit-code
exit "$rc"
"""
        (job_dir / "runner.sh").write_text(runner, encoding="utf-8")

    def _grant_job_user_access(self, job_dir: Path) -> None:
        if not self.job_user or os.geteuid() != 0:
            return
        account = pwd.getpwnam(self.job_user)
        for path in [job_dir, *job_dir.rglob("*")]:
            os.chown(path, account.pw_uid, account.pw_gid)

    def _write_record(self, job_id: str, record: dict[str, Any]) -> None:
        path = self.root / job_id / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _valid_id(job_id: str) -> bool:
        return len(job_id) == 12 and all(char in "0123456789abcdef" for char in job_id)


agent_jobs = AgentJobManager()
