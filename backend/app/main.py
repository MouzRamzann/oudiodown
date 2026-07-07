from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
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

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(
    title="Oudiodown API",
    description="Convert Instagram Reels to downloadable MP3 audio.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ConvertRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Instagram Reel or Post URL")


class ConvertResponse(BaseModel):
    id: str
    title: str
    download_url: str


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/convert", response_model=ConvertResponse)
def convert(payload: ConvertRequest, background_tasks: BackgroundTasks) -> ConvertResponse:
    background_tasks.add_task(cleanup_old_files)

    try:
        result = convert_reel_to_mp3(payload.url)
    except InvalidUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface a safe generic message
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while converting. Please try again.",
        ) from exc

    return ConvertResponse(
        id=result["id"],
        title=result["title"],
        download_url=f"/api/download/{result['id']}",
    )


@app.get("/api/download/{job_id}")
def download(job_id: str) -> FileResponse:
    path = get_file_path(job_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found or has expired.")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename="oudiodown-track.mp3",
    )


# Serve the static frontend last so /api/* routes above always take priority.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
