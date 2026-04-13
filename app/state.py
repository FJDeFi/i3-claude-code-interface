import uuid
from typing import Dict
from .models import Job

jobs: Dict[str, Job] = {}


def create_job(prompt: str) -> Job:
    job_id = str(uuid.uuid4())
    job = Job(id=job_id, prompt=prompt)
    jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job:
    return jobs.get(job_id)


def get_pending_job():
    for job in jobs.values():
        if job.status == "pending":
            return job
    return None
