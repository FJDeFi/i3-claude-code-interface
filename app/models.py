from pydantic import BaseModel
from typing import Optional


class Job(BaseModel):
    id: str
    prompt: str
    status: str = "pending"  # pending, running, done
    result: Optional[str] = None
