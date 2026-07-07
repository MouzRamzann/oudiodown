"""In-memory job store for async conversion tasks."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

JOB_TTL = 2 * 60 * 60  # keep job records for 2 hours


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    title: str = ""
    download_url: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)


_store: dict[str, Job] = {}
_lock = asyncio.Lock()


async def create_job() -> Job:
    job = Job(id=uuid.uuid4().hex)
    async with _lock:
        _store[job.id] = job
    return job


async def get_job(job_id: str) -> Optional[Job]:
    return _store.get(job_id)


async def update_job(job_id: str, **kwargs) -> None:
    async with _lock:
        job = _store.get(job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)


async def expire_old_jobs() -> None:
    cutoff = time.time() - JOB_TTL
    async with _lock:
        stale = [jid for jid, j in _store.items() if j.created_at < cutoff]
        for jid in stale:
            del _store[jid]
