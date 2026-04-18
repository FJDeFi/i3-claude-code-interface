from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .state import create_job, get_job

app = FastAPI()
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


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
