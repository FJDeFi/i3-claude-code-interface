import time
from .state import claim_pending_job, update_job
from .claude import run_claude


def worker_loop():
    print("Worker started...")

    while True:
        job = claim_pending_job()

        if job:
            print(f"Running job {job.id}")

            try:
                result = run_claude(job.prompt)
                update_job(job.id, "done", result)
            except Exception as e:
                update_job(job.id, "failed", str(e))

        time.sleep(1)
