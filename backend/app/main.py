from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .downloader import (
    ConversionError,
    InvalidUrlError,
    cleanup_old_files,
    convert_reel_to_mp3,
    get_file_path,
)
from .jobs import JobStatus, create_job, expire_old_jobs, get_job, update_job

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# ---------------------------------------------------------------------------
# Per-IP rate limiting (in-memory, resets on restart)
# ---------------------------------------------------------------------------
_ip_hits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 10   # requests
RATE_WINDOW = 60  # seconds


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    cutoff = now - RATE_WINDOW
    hits = [t for t in _ip_hits[ip] if t > cutoff]
    _ip_hits[ip] = hits
    if len(hits) >= RATE_LIMIT:
        return False
    _ip_hits[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Oudiodown API",
    description="Convert Instagram Reels to downloadable MP3.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ConvertRequest(BaseModel):
    url: str = Field(..., min_length=1)


class ConvertResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: JobStatus
    title: str = ""
    download_url: str = ""
    error: str = ""


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/convert", response_model=ConvertResponse, status_code=202)
async def convert(payload: ConvertRequest, request: Request) -> ConvertResponse:
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

    job = await create_job()
    asyncio.create_task(_run_conversion(job.id, payload.url))
    return ConvertResponse(job_id=job.id)


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def status(job_id: str) -> StatusResponse:
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return StatusResponse(
        status=job.status,
        title=job.title,
        download_url=job.download_url,
        error=job.error,
    )


@app.get("/api/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    path = get_file_path(job_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found or has expired.")
    return FileResponse(path, media_type="audio/mpeg", filename="oudiodown-track.mp3")


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------
async def _run_conversion(job_id: str, url: str) -> None:
    await update_job(job_id, status=JobStatus.PROCESSING)
    try:
        result = await convert_reel_to_mp3(url, job_id)
        await update_job(
            job_id,
            status=JobStatus.DONE,
            title=result["title"],
            download_url=f"/api/download/{job_id}",
        )
    except (InvalidUrlError, ConversionError) as exc:
        await update_job(job_id, status=JobStatus.ERROR, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        await update_job(
            job_id,
            status=JobStatus.ERROR,
            error="Something went wrong. Please try again.",
        )
    finally:
        cleanup_old_files()
        asyncio.create_task(expire_old_jobs())


# Serve the static frontend — must be mounted last.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
