from typing import Literal, Optional

from pydantic import BaseModel

JobStatus = Literal["pending", "running", "done", "failed"]


class Job(BaseModel):
    id: str
    prompt: str
    status: JobStatus = "pending"
    result: Optional[str] = None
