import time

from .agent import agent_loop
from .state import claim_pending_job, update_job


def worker_loop() -> None:
    print("Worker started...")

    while True:
        job = claim_pending_job()

        if job:
            print(f"Running job {job.id}")

            try:
                result = agent_loop(job.prompt)
                update_job(job.id, "done", result)
            except Exception as exc:
                update_job(job.id, "failed", str(exc))

        time.sleep(1)
