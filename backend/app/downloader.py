"""Core logic for turning an Instagram Reel URL into a downloadable MP3."""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp

# Path to a Netscape-format cookies.txt file exported from a logged-in
# Instagram browser session.  Instagram requires authentication for most
# content when accessed via automated tools.
# Export with: "Get cookies.txt LOCALLY" browser extension → instagram.com
COOKIES_FILE = os.environ.get("INSTAGRAM_COOKIES_FILE", "")

INSTAGRAM_URL_RE = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|reels|p|tv)/[\w-]+/?", re.IGNORECASE
)
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_AGE_SECONDS = 60 * 60  # 1 hour retention for generated MP3s


class InvalidUrlError(Exception):
    """Raised when the supplied URL is not a supported Instagram link."""


class ConversionError(Exception):
    """Raised when yt-dlp fails to fetch or convert the media."""


def is_valid_instagram_url(url: str) -> bool:
    return bool(INSTAGRAM_URL_RE.match(url.strip()))


def convert_reel_to_mp3(url: str) -> dict:
    """Download the given Instagram Reel/Post and extract its audio as MP3.

    Returns a dict with the generated job id, a sanitized title, and the
    path to the resulting MP3 file.
    """
    url = url.strip()
    if not is_valid_instagram_url(url):
        raise InvalidUrlError(
            "That doesn't look like a valid Instagram Reel or Post URL."
        )

    job_id = uuid.uuid4().hex
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    cookies_path = Path(COOKIES_FILE) if COOKIES_FILE else None
    if cookies_path and cookies_path.is_file():
        ydl_opts["cookiefile"] = str(cookies_path)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if "login required" in msg or "rate-limit" in msg or "not available" in msg:
            raise ConversionError(
                "Instagram requires a logged-in session to access this content. "
                "The server needs a valid cookies file configured via "
                "INSTAGRAM_COOKIES_FILE. See README for setup instructions."
            ) from exc
        raise ConversionError(
            "We couldn't fetch that reel. It may be private or deleted."
        ) from exc

    mp3_path = DOWNLOAD_DIR / f"{job_id}.mp3"
    if not mp3_path.exists():
        raise ConversionError("No audio track was found in that post.")

    raw_title = (info or {}).get("title") or (info or {}).get("description") or "oudiodown_track"
    safe_title = re.sub(r"[^\w\-. ]+", "", raw_title).strip()[:80] or "oudiodown_track"

    return {"id": job_id, "title": safe_title, "path": mp3_path}


def get_file_path(job_id: str) -> Optional[Path]:
    if not JOB_ID_RE.fullmatch(job_id):
        return None
    path = DOWNLOAD_DIR / f"{job_id}.mp3"
    return path if path.exists() else None


def cleanup_old_files(max_age_seconds: int = MAX_FILE_AGE_SECONDS) -> None:
    """Delete generated MP3s older than max_age_seconds to save disk space."""
    now = time.time()
    for f in DOWNLOAD_DIR.glob("*.mp3"):
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
        except OSError:
            continue
