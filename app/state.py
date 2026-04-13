import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Optional

from .models import Job, JobStatus

DB_PATH = os.getenv(
    "JOB_DB_PATH", str(Path(__file__).resolve().parent / "jobs.db")
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        prompt=row["prompt"],
        status=row["status"],
        result=row["result"],
    )


def _init_db() -> None:
    with closing(_get_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


_init_db()


def create_job(prompt: str) -> Job:
    job = Job(id=str(uuid.uuid4()), prompt=prompt)
    with closing(_get_conn()) as conn:
        conn.execute(
            "INSERT INTO jobs (id, prompt, status, result) VALUES (?, ?, ?, ?)",
            (job.id, job.prompt, job.status, job.result),
        )
        conn.commit()
    return job


def get_job(job_id: str) -> Optional[Job]:
    with closing(_get_conn()) as conn:
        row = conn.execute(
            "SELECT id, prompt, status, result FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_job(row)


def claim_pending_job() -> Optional[Job]:
    with closing(_get_conn()) as conn:
        row = conn.execute(
            """
            SELECT id, prompt, status, result
            FROM jobs
            WHERE status = 'pending'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()

        if not row:
            return None

        updated = conn.execute(
            "UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'pending'",
            (row["id"],),
        )
        conn.commit()

        if updated.rowcount != 1:
            return None

    return Job(
        id=row["id"],
        prompt=row["prompt"],
        status="running",
        result=row["result"],
    )


def update_job(job_id: str, status: JobStatus, result: Optional[str] = None) -> None:
    with closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, result = ? WHERE id = ?",
            (status, result, job_id),
        )
        conn.commit()
