from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from app.agent_jobs import AgentJobManager
import pytest


def test_create_job_saves_inputs_and_runner(tmp_path):
    manager = AgentJobManager(tmp_path, job_user="", claude_cmd="claude")
    job = manager.create_job(
        "Improve data",
        "Read the input and improve it.",
        [("../data.json", b'{"value": 1}')],
    )

    job_dir = tmp_path / job["id"]
    assert job["status"] == "queued"
    assert job["files"] == ["data.json"]
    assert (job_dir / "input" / "data.json").read_bytes() == b'{"value": 1}'
    runner = (job_dir / "runner.sh").read_text()
    assert "claude -p" in runner
    assert "--dangerously-skip-permissions" in runner
    assert "output/response.txt" in runner


def test_worker_completes_jobs_one_at_a_time(tmp_path):
    class FakeManager(AgentJobManager):
        def __init__(self, root: Path):
            super().__init__(root, job_user="", poll_seconds=0.001, timeout_seconds=2)
            self.started: list[str] = []

        async def _tmux(self, *args: str, check: bool):
            if args[0] == "send-keys":
                job_id = args[2].removeprefix("i3-job-")
                self.started.append(job_id)
                job_dir = self.root / job_id
                (job_dir / "output" / "summary.md").write_text("done")
                (job_dir / "exit-code").write_text("0\n")
            return subprocess.CompletedProcess(args, 0, "", "")

    manager = FakeManager(tmp_path)
    first = manager.create_job("First", "Do first", [])
    second = manager.create_job("Second", "Do second", [])
    asyncio.run(_wait_for_worker(manager))

    assert manager.started == [first["id"], second["id"]]
    assert manager.get_job(first["id"])["status"] == "completed"
    assert manager.get_job(second["id"])["status"] == "completed"


async def _wait_for_worker(manager: AgentJobManager) -> None:
    manager.ensure_worker()
    assert manager._worker_task is not None
    await manager._worker_task


def test_result_archive_contains_output_only(tmp_path):
    manager = AgentJobManager(tmp_path, job_user="")
    job = manager.create_job("Archive", "Create output", [])
    record = manager.get_job(job["id"])
    record["status"] = "completed"
    manager._write_record(job["id"], record)
    (tmp_path / job["id"] / "output" / "result.txt").write_text("result")

    archive = manager.result_archive(job["id"])
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["result.txt"]
        assert bundle.read("result.txt") == b"result"


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_real_tmux_pipeline_with_fake_claude(tmp_path):
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        "#!/bin/bash\n"
        "mkdir -p output\n"
        "printf 'HELLO\\n' > output/result.txt\n"
        "printf 'fake Claude completed\\n'\n"
    )
    fake_claude.chmod(0o755)
    manager = AgentJobManager(
        tmp_path / "jobs",
        job_user="",
        claude_cmd=str(fake_claude),
        poll_seconds=0.05,
        timeout_seconds=5,
    )
    job = manager.create_job("Smoke test", "Uppercase the input", [("hello.txt", b"hello\n")])

    asyncio.run(_wait_for_worker(manager))

    completed = manager.get_job(job["id"])
    assert completed["status"] == "completed"
    assert (manager.root / job["id"] / "output" / "result.txt").read_text() == "HELLO\n"
    assert "fake Claude completed" in manager.log_text(job["id"])
