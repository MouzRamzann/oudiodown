# Oudiodown

Convert public Instagram Reels to MP3 audio. HTML/CSS/JS frontend, FastAPI backend.

## Stack

- **Backend**: FastAPI + [yt-dlp](https://github.com/yt-dlp/yt-dlp) (fetches the Reel and extracts audio) + ffmpeg (audio conversion)
- **Frontend**: Static HTML/CSS/JS, served directly by FastAPI (no build step)

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on `PATH` (required by yt-dlp's audio extraction)

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Instagram cookies (required)

Instagram blocks unauthenticated automated requests. You must supply a cookies file from a logged-in browser session:

1. Install the **"Get cookies.txt LOCALLY"** extension in Chrome or Firefox
2. Log into instagram.com
3. Click the extension and export cookies for `instagram.com` — save the file somewhere (e.g. `~/instagram_cookies.txt`)
4. Set the env var before starting the server:

```bash
export INSTAGRAM_COOKIES_FILE=~/instagram_cookies.txt
```

Or copy `.env.example` to `.env` and fill it in, then load it with:

```bash
export $(cat .env | xargs)
```

Cookies expire over time — re-export them if you start getting auth errors again.

## Run

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 — the frontend is served at `/`, the API under `/api`.

## API

- `POST /api/convert` — body `{"url": "https://www.instagram.com/reel/..."}` → `{"id", "title", "download_url"}`
- `GET /api/download/{id}` — streams the generated MP3
- `GET /api/health` — health check

Generated MP3 files are stored in `backend/downloads/` and automatically deleted after 1 hour.

## Deploying to oudiodown.com

Any host that can run a Python/ASGI app with ffmpeg installed works (e.g. a VM, Docker container, or PaaS with a custom buildpack that installs ffmpeg). Point the domain's DNS at the server running `uvicorn`/`gunicorn`, and put a reverse proxy (nginx/Caddy) in front for HTTPS.

## Notes

- Only public Reels/posts can be converted — private content isn't supported.
- This tool is intended for personal use; respect creators' rights and Instagram's terms when downloading content.
