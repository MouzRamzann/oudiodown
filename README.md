# Oudiodown

Convert public Instagram Reels to MP3 audio. HTML/CSS/JS frontend, FastAPI backend.

## Stack

- **Backend**: FastAPI + httpx (async) + ffmpeg (audio extraction)
- **Instagram data**: [RapidAPI — Instagram Scraper API 2](https://rapidapi.com/search/instagram-scraper-api2) — handles all Instagram auth, no cookies needed
- **Frontend**: Static HTML/CSS/JS, served by FastAPI (no build step)

## How it works

1. User pastes a Reel URL → frontend POSTs to `/api/convert` and gets a `job_id` back immediately (non-blocking)
2. Backend fetches the Reel's video URL via RapidAPI, downloads it, and runs ffmpeg to extract a 192kbps MP3
3. Frontend polls `/api/status/{job_id}` every 2 seconds until `done`
4. User downloads the MP3 via `/api/download/{job_id}`
5. Files are automatically deleted after 1 hour

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) installed and on `PATH`
- A [RapidAPI](https://rapidapi.com) account with a subscription to **Instagram Scraper API 2**

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your RAPIDAPI_KEY
export $(cat .env | xargs)
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 — frontend at `/`, API at `/api`.

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/convert` | Start a conversion job → `{"job_id": "..."}` |
| `GET` | `/api/status/{id}` | Poll job status → `{status, title, download_url, error}` |
| `GET` | `/api/download/{id}` | Download the generated MP3 |
| `GET` | `/api/health` | Health check |

## Rate limiting

10 requests per IP per 60 seconds (in-memory, resets on restart).

## Deploying

Any host that runs Python/ASGI with ffmpeg:
- Set `RAPIDAPI_KEY` as an environment variable on the server
- Put nginx/Caddy in front for HTTPS and reverse-proxy to `uvicorn`/`gunicorn`

No cookies, no Instagram accounts, no session management needed.
