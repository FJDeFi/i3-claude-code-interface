import time
from .state import get_pending_job
from .claude import run_claude


def worker_loop():
    print("Worker started...")

    while True:
        job = get_pending_job()

        if job:
            print(f"Running job {job.id}")
            job.status = "running"

            try:
                result = run_claude(job.prompt)
                job.result = result
                job.status = "done"
            except Exception as e:
                job.result = str(e)
                job.status = "failed"

        time.sleep(1)
