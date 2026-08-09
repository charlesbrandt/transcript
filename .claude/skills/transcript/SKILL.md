---
name: transcript
description: Get oriented with the transcript project — FastAPI + Svelte web UI for transcript editing and audio re-rendering; runs on GPU machine (192.168.2.99); API on :8400, frontend on :3006
---

# Transcript — Project Orientation

**Repo:** `~/repos/transcript`
**CWD when this skill runs:** `/home/account/repos/transcript`

## What it is

A toolkit for editing media files by manipulating their transcripts. The CLI (`editor.py`) is the primary batch interface; the web UI wraps it for interactive editing of individual files — particularly voice notes routed through disptch.

**Workflow:**
1. **checkout** — create `.edit.md` editable transcript from a whisper metadata JSON
2. **diff** — word-level comparison of original vs edited text; shows what will be cut
3. **render** — ffmpeg re-renders the media keeping only the specified words (with padding)
4. **retranscribe** — re-runs ASR on the rendered output for fresh timestamps

## Deployment (GPU machine — 192.168.2.99)

- **API:** `http://192.168.2.99:8400` (FastAPI + uvicorn)
- **Frontend:** `http://192.168.2.99:3006` (Svelte 4 + Vite dev server)
- Repo cloned at `~/repos/transcript/` on GPU machine

To deploy after pushing changes:
```bash
ssh account@192.168.2.99 "cd ~/repos/transcript && git pull && docker compose up -d --build api ui"
```

**Note:** The GPU machine may have uncommitted local changes. If `git pull` fails:
```bash
ssh account@192.168.2.99 "cd ~/repos/transcript && git stash && git pull && docker compose up -d --build api ui"
```

## Stack

- **Backend:** FastAPI (`api.py`) — wraps `transcript_editor/editor.py` functions over HTTP
- **Frontend:** Svelte 4 + Vite (`ui/`) — single-view SPA; wavesurfer.js waveform player
- **Runtime:** Docker Compose — `docker compose up -d api ui`
  - `api` → port 8400 (host) / 8000 (container); built from root `Dockerfile`
  - `ui` → port 3006 (host) / 5173 (container); built from `ui/Dockerfile`
  - `app` → legacy CLI container, only started with `--profile cli`

## API endpoints

```
GET  /status                         health check
GET  /session?metadata=<abs-path>    checkout (returns existing .edit.md or creates); returns edit_text + segments + media_path
POST /diff                           stateless word diff; body: {metadata_path, edit_text}; returns aligned_words + time_saved
POST /render                         write .edit.md + run ffmpeg; body: {metadata_path, edit_text, padding}; SSE stream
POST /retranscribe                   re-run ASR on rendered output; body: {metadata_path}; SSE stream
GET  /media?path=<abs-path>          stream audio/video with Range support
```

`GET /session` is **resumable** — if a `.edit.md` already exists it returns the current contents without overwriting. `POST /render` is the only endpoint that writes the `.edit.md` to disk.

## Frontend usage

Open `http://192.168.2.99:3006/?metadata=/absolute/path/to/file-metadata.json`

Or type the metadata path into the text input and click Load. The `?metadata=` query param is set in the URL after loading, so the browser tab can be bookmarked/shared.

**Integration with say-what / disptch:** a "Refine" deep-link from those UIs passes `?metadata=<path>` to open a specific recording directly in the editor.

## File layout

```
transcript/
├── api.py                          # FastAPI app (all endpoints)
├── Dockerfile                      # Python 3.10-slim + ffmpeg + uv
├── docker-compose.yml              # api + ui services; app as --profile cli
├── docker-compose.override.yml     # host volume mounts (gitignored):
│                                   #   /media/other:/data, /media/memory:/memory
├── requirements.txt                # fastapi, uvicorn[standard], python-multipart, requests
├── transcript_editor/
│   ├── editor.py                   # checkout, diff, render, retranscribe functions
│   └── transcriber.py              # ASR upload / chunking
└── ui/
    ├── src/
    │   ├── App.svelte              # single-view app; session load, edit, render flow
    │   ├── lib/api.ts              # typed fetch wrappers for all endpoints
    │   └── components/
    │       ├── WaveformPlayer.svelte  # wavesurfer.js; exposes seekTo(seconds)
    │       ├── SegmentList.svelte     # timestamped segments; click-to-seek
    │       └── DiffPanel.svelte       # word-level keep/remove visualization
    ├── vite.config.ts              # proxies /api/* → http://api:8000
    └── Dockerfile                  # node:20-slim; npm install + npm run dev
```

## Volume mounts (override file on GPU machine)

Media files on the GPU machine are accessed via these mounts in `docker-compose.override.yml`:
- `/media/other:/data:cached`
- `/media/memory:/memory:cached`

Metadata paths passed to `GET /session` must be absolute paths **inside the container** (i.e. starting with `/data/` or `/memory/`, not host paths like `/media/other/`).

## Environment variables (`.env`)

```
ASR_API_BASE=http://192.168.2.99:9000   # whisper-asr endpoint
UID=1000
GID=1000
```

## Troubleshooting

**UI shows "unhealthy" in `docker ps`:** The healthcheck uses `wget` which isn't in the node:slim image. Functionally working — same situation as digger.

**`/session` returns 404:** The metadata path must be an absolute path inside the container. If the file is at `/media/other/foo-metadata.json` on the host, pass `/data/foo-metadata.json`.

**Render hangs:** ffmpeg is running in `asyncio.to_thread`. Check API logs: `docker compose logs -f api`.

**Containers not running:**
```bash
ssh account@192.168.2.99 "docker ps | grep transcript"
ssh account@192.168.2.99 "docker compose -f ~/repos/transcript/docker-compose.yml logs --tail=50 api"
```
