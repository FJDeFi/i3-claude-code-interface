from fastapi import FastAPI, HTTPException

from .state import create_job, get_job

app = FastAPI()


@app.post("/prompt")
def submit(prompt: str):
    job = create_job(prompt)
    return {"job_id": job.id}


@app.get("/result/{job_id}")
def result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")

    return {"status": job.status, "result": job.result}
