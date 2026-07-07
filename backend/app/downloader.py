"""Fetch Instagram Reel audio via RapidAPI (instagram120) and convert to MP3."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx

# instagram120.p.rapidapi.com — POST /api/instagram/links, body {"url": "<reel_url>"}
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "instagram120.p.rapidapi.com")
RAPIDAPI_ENDPOINT = os.environ.get("RAPIDAPI_ENDPOINT", "/api/instagram/links")

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


def clean_instagram_url(url: str) -> str:
    """Strip query params/fragments so the API gets a clean URL."""
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", "")).rstrip("/") + "/"


async def _fetch_reel_info(url: str) -> dict:
    """POST to RapidAPI and return {'video_url': ..., 'title': ..., 'needs_auth': bool}."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        raise ConversionError("Server is missing RAPIDAPI_KEY. Contact the site administrator.")

    api_host = os.environ.get("RAPIDAPI_HOST", RAPIDAPI_HOST)
    api_endpoint = os.environ.get("RAPIDAPI_ENDPOINT", RAPIDAPI_ENDPOINT)
    clean_url = clean_instagram_url(url)

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://{api_host}{api_endpoint}",
            json={"url": clean_url},
            headers=headers,
        )

    print(f"=== RAPIDAPI STATUS: {resp.status_code} | url: {clean_url} ===")
    print(resp.text[:4000])
    print("==========================================")

    if resp.status_code == 401:
        raise ConversionError("RapidAPI key is invalid or expired.")
    if resp.status_code == 429:
        raise ConversionError("Too many requests. Please try again in a moment.")
    if resp.status_code == 403:
        raise ConversionError("Not subscribed to this API. Check your RapidAPI subscription.")

    try:
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise ConversionError(f"Scraper API returned status {resp.status_code}.") from exc

    # Response is a JSON array of media items
    if not isinstance(payload, list) or not payload:
        raise ConversionError("That Reel couldn't be found. It may be private or deleted.")

    # Find the best MP4 item
    video_url, needs_auth = _pick_mp4(payload, api_host)
    if not video_url:
        raise ConversionError("No video found in that post — it may be a photo only.")

    # Extract title from first item's meta
    title = ""
    for item in payload:
        meta = item.get("meta") or {}
        title = (meta.get("title") or "").strip()
        if title:
            break
    safe_title = re.sub(r"[^\w\-. ]+", "", title).strip()[:80] or "oudiodown_track"

    return {"video_url": video_url, "title": safe_title, "needs_auth": needs_auth, "api_host": api_host}


def _pick_mp4(items: list, api_host: str) -> tuple[Optional[str], bool]:
    """Find the best MP4 URL. Returns (url, needs_api_auth).
    Relative URLs (/api/instagram/get?...) must be downloaded with the API key header."""
    for item in items:
        for u in item.get("urls", []):
            if isinstance(u, dict) and u.get("extension", "").lower() == "mp4":
                raw = u.get("url", "")
                if raw.startswith("http"):
                    return raw, False
                # Relative proxy URL — prepend the API host
                return f"https://{api_host}{raw}", True
    return None, False


async def convert_reel_to_mp3(url: str, job_id: str) -> dict:
    """Full pipeline: fetch info → download video → ffmpeg → MP3."""
    url = url.strip()
    if not is_valid_instagram_url(url):
        raise InvalidUrlError("That doesn't look like a valid Instagram Reel URL.")

    info = await _fetch_reel_info(url)

    api_key = os.environ.get("RAPIDAPI_KEY", "")
    download_headers = {}
    if info.get("needs_auth"):
        download_headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": info["api_host"],
        }

    tmp_video = Path(tempfile.mktemp(suffix=".mp4"))
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", info["video_url"], headers=download_headers) as resp:
                resp.raise_for_status()
                with open(tmp_video, "wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        fh.write(chunk)

        mp3_path = DOWNLOAD_DIR / f"{job_id}.mp3"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ffmpeg_extract, tmp_video, mp3_path)

    finally:
        tmp_video.unlink(missing_ok=True)

    return {"title": info["title"], "path": mp3_path}


def _ffmpeg_extract(src: Path, dst: Path) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "libmp3lame", "-ab", "192k", str(dst)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise ConversionError(
            "Audio extraction failed: " + result.stderr.decode(errors="replace")[:300]
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
