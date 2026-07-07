"""Core logic for turning an Instagram Reel URL into a downloadable MP3."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp

# Path to a cookies file (Netscape .txt OR JSON array from browser extensions
# like EditThisCookie / Cookie-Editor).  JSON is converted automatically.
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


def _json_cookies_to_netscape(json_path: Path) -> Path:
    """Convert a JSON cookie array (EditThisCookie / Cookie-Editor format)
    to a Netscape cookies.txt file.  Returns the path to the temp file."""
    cookies = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(cookies, list):
        raise ValueError("Expected a JSON array of cookie objects.")

    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.get("domain", "")
        # Netscape format requires a leading dot for subdomain-matching cookies
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expiry = int(c.get("expirationDate", 0) or c.get("expires", 0) or 0)
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return Path(tmp.name)


def _resolve_cookies_path(raw: str) -> Optional[str]:
    """Return a path to a Netscape cookies file, converting JSON if needed."""
    p = Path(raw)
    if not p.is_file():
        return None
    try:
        json.loads(p.read_text(encoding="utf-8"))
        # It's valid JSON — convert it
        return str(_json_cookies_to_netscape(p))
    except (json.JSONDecodeError, ValueError):
        # Already Netscape format
        return str(p)


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

    if COOKIES_FILE:
        resolved = _resolve_cookies_path(COOKIES_FILE)
        if resolved:
            ydl_opts["cookiefile"] = resolved

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
