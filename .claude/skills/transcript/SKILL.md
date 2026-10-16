---
name: transcript
description: Get oriented with the transcript project — FastAPI + Svelte web UI for transcript editing and audio re-rendering; runs as Docker Compose services on a GPU host; API on :8400, frontend on :3006; optional speaker diarization
---

# Transcript — Project Orientation

**Repo:** the checkout this skill lives in (`.claude/skills/transcript/`)
**Local details:** host names, addresses and mount paths are deliberately not in this file. If `.claude/skills/transcript/LOCAL.md` exists (gitignored), read it for this machine's deployment details.

## What it is

A toolkit for editing media files by manipulating their transcripts. The CLI (`editor.py`) is the primary batch interface; the web UI wraps it for interactive editing of individual files — particularly voice notes routed through disptch.

**Workflow:**
1. **checkout** — create `.edit.md` editable transcript from a whisper metadata JSON
2. **diff** — word-level comparison of original vs edited text; shows what will be cut
3. **render** — ffmpeg re-renders the media keeping only the specified words (with padding)
4. **retranscribe** — re-runs ASR on the rendered output for fresh timestamps

## Deployment

- **API:** `http://<host>:8400` (FastAPI + uvicorn)
- **Frontend:** `http://<host>:3006` (Svelte 4 + Vite dev server)
- `<host>` is the machine running the compose stack (a GPU box with the ASR service nearby)

To deploy after pushing changes:
```bash
ssh <user>@<host> "cd <repo-path> && git pull && docker compose up -d --build api ui"
```

**Note:** The deploy host may have uncommitted local changes. If `git pull` fails, `git stash` first.

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

Open `http://<host>:3006/?metadata=/absolute/path/to/file-metadata.json`

Or type the metadata path into the text input and click Load. The `?metadata=` query param is set in the URL after loading, so the browser tab can be bookmarked/shared.

**Integration with say-what / disptch:** a "Refine" deep-link from those UIs passes `?metadata=<path>` to open a specific recording directly in the editor.

## File layout

```
transcript/
├── api.py                          # FastAPI app (all endpoints)
├── Dockerfile                      # Python 3.10-slim + ffmpeg + uv
├── docker-compose.yml              # api + ui services; app as --profile cli
├── docker-compose.override.yml     # host volume mounts (gitignored), e.g.
│                                   #   /path/to/media:/data
├── requirements.txt                # fastapi, uvicorn[standard], python-multipart, requests
├── transcript_editor/
│   ├── editor.py                   # checkout, diff, render, retranscribe functions
│   ├── transcriber.py              # ASR upload / chunking (the only transcriber module)
│   └── diarization.py              # optional speaker labelling via a diarize sidecar
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

## Volume mounts (override file on the deploy host)

Media directories are mounted into the `api` container in a gitignored `docker-compose.override.yml`, e.g. `/path/on/host:/data:cached`.

Metadata paths passed to `GET /session` must be absolute paths **inside the container** (e.g. starting with `/data/`), not host paths.

## Environment variables (`.env`)

```
ASR_API_BASE=http://<asr-host>:9000     # whisper-asr endpoint
DIARIZE_API_BASE=http://<diarize-host>:9003   # optional: pyannote diarize sidecar; enables speaker labels
UID=1000
GID=1000
```

## Troubleshooting

**UI shows "unhealthy" in `docker ps`:** The healthcheck uses `wget` which isn't in the node:slim image. Functionally working — same situation as digger.

**`/session` returns 404:** The metadata path must be an absolute path inside the container. If the file is `<host-dir>/foo-metadata.json` on the host and `<host-dir>` is mounted at `/data`, pass `/data/foo-metadata.json`.

**Render hangs:** ffmpeg is running in `asyncio.to_thread`. Check API logs: `docker compose logs -f api`.

**Containers not running:**
```bash
ssh <user>@<host> "docker ps | grep transcript"
ssh <user>@<host> "docker compose -f <repo-path>/docker-compose.yml logs --tail=50 api"
```

## Speaker diarization (optional)

Off unless enabled. Set `DIARIZE_API_BASE` (or pass `--diarize`) and the transcriber sends the whole file once to a pyannote sidecar (`POST /diarize`), then gives each word the speaker whose turn overlaps it most. Labels are generic `A`, `B`, `C`... in order of first appearance, stored as a `speaker` field on every word and segment in `*-metadata.json`; the web UI shows the segment speaker next to each segment.

```bash
python -m transcript_editor.transcriber -f meeting.wav --enable-splitting --diarize [--min-speakers 2 --max-speakers 6]
```

- Diarization is one pass over the full file, never per chunk, so labels stay consistent when `--enable-splitting` is on.
- It never blocks transcription: if the sidecar is unset, unreachable or errors, a warning is logged and the transcript is written without speakers.
- The `.edit.md` workflow ignores speakers (it is word-diffed); the code is in `transcript_editor/diarization.py`, tests in `test_diarization.py`.
- With speakers, it also writes `<stem>-transcript-speakers.md` (one `**A** (hh:mm:ss): ...` paragraph per turn); regenerate it from existing metadata with `python -m transcript_editor.diarization <stem>-metadata.json`.
- The console prints whether speakers were labelled; the reason for any failure is in `processing.log` beside the recording.
- Speaker labels are anonymous. Mapping them to real names is outside this project.
- Segment boundaries depend on the ASR service version; re-baseline anything keyed to old segment timings after upgrading it.
