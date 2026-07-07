"""Fetch Instagram Reel audio via RapidAPI and convert to MP3 with ffmpeg."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "instagram-scraper-stable-api.p.rapidapi.com")
# Endpoint path for fetching reel/post data — override via RAPIDAPI_ENDPOINT env var
RAPIDAPI_ENDPOINT = os.environ.get("RAPIDAPI_ENDPOINT", "/get_media_data.php")

INSTAGRAM_URL_RE = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|reels|p|tv)/[\w-]+/?", re.IGNORECASE
)
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_AGE_SECONDS = 60 * 60


class InvalidUrlError(Exception):
    pass


class ConversionError(Exception):
    pass


def is_valid_instagram_url(url: str) -> bool:
    return bool(INSTAGRAM_URL_RE.match(url.strip()))


async def _fetch_reel_info(url: str) -> dict:
    """Call RapidAPI and return {'video_url': ..., 'title': ...}."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        raise ConversionError(
            "Server is missing RAPIDAPI_KEY. Contact the site administrator."
        )

    api_host = os.environ.get("RAPIDAPI_HOST", RAPIDAPI_HOST)
    api_endpoint = os.environ.get("RAPIDAPI_ENDPOINT", RAPIDAPI_ENDPOINT)
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://{api_host}{api_endpoint}",
            params={"reel_post_code_or_url": url, "type": "reel"},
            headers=headers,
        )

    # DEBUG — always print raw response so we can fix the parser
    print(f"=== RAPIDAPI STATUS: {resp.status_code} ===")
    print(resp.text[:3000])
    print("==========================================")

    if resp.status_code == 401:
        raise ConversionError("RapidAPI key is invalid or expired.")
    if resp.status_code == 429:
        raise ConversionError("Too many requests. Please try again in a moment.")
    if resp.status_code == 404:
        raise ConversionError("That Reel wasn't found. It may be private or deleted.")

    try:
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise ConversionError(f"Scraper API returned status {resp.status_code}.") from exc

    data = payload.get("data") or {}

    # Grab the best available video URL
    video_url = (
        data.get("video_url")
        or _pick_from_versions(data.get("video_versions"))
    )
    if not video_url:
        raise ConversionError(
            "No video found in that post — it may be a photo or carousel."
        )

    raw_caption = data.get("caption") or {}
    raw_text = (
        raw_caption.get("text") if isinstance(raw_caption, dict) else str(raw_caption)
    ) or "oudiodown_track"
    title = re.sub(r"[^\w\-. ]+", "", raw_text).strip()[:80] or "oudiodown_track"

    return {"video_url": video_url, "title": title}


def _pick_from_versions(versions) -> Optional[str]:
    if not isinstance(versions, list) or not versions:
        return None
    # Prefer highest width
    best = max(versions, key=lambda v: v.get("width", 0) if isinstance(v, dict) else 0)
    return best.get("url") if isinstance(best, dict) else None


async def convert_reel_to_mp3(url: str, job_id: str) -> dict:
    """Full pipeline: fetch → download → ffmpeg → MP3. Returns title."""
    url = url.strip()
    if not is_valid_instagram_url(url):
        raise InvalidUrlError("That doesn't look like a valid Instagram Reel URL.")

    info = await _fetch_reel_info(url)

    tmp_video = Path(tempfile.mktemp(suffix=".mp4"))
    try:
        # Stream-download the video file
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", info["video_url"]) as resp:
                resp.raise_for_status()
                with open(tmp_video, "wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        fh.write(chunk)

        mp3_path = DOWNLOAD_DIR / f"{job_id}.mp3"

        # Run ffmpeg in a thread so we don't block the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ffmpeg_extract, tmp_video, mp3_path)

    finally:
        tmp_video.unlink(missing_ok=True)

    return {"title": info["title"], "path": mp3_path}


def _ffmpeg_extract(src: Path, dst: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-vn", "-acodec", "libmp3lame", "-ab", "192k",
            str(dst),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise ConversionError(
            "Audio extraction failed — ffmpeg error: "
            + result.stderr.decode(errors="replace")[:300]
        )


def get_file_path(job_id: str) -> Optional[Path]:
    if not JOB_ID_RE.fullmatch(job_id):
        return None
    path = DOWNLOAD_DIR / f"{job_id}.mp3"
    return path if path.exists() else None


def cleanup_old_files(max_age: int = MAX_FILE_AGE_SECONDS) -> None:
    now = time.time()
    for f in DOWNLOAD_DIR.glob("*.mp3"):
        try:
            if now - f.stat().st_mtime > max_age:
                f.unlink(missing_ok=True)
        except OSError:
            continue
