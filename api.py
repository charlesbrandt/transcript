"""
Transcript Editor Web API — run with: uvicorn api:app --reload

Endpoints:
  GET /session?metadata=<path>   checkout transcript; returns edit text + segments
  POST /diff                     stateless diff; returns word-level keep/remove list
  POST /render                   write .edit.md, run ffmpeg; streams SSE progress
  POST /retranscribe             re-run ASR on rendered output; streams SSE
  GET /media?path=<path>         stream audio/video with Range support
  GET /status                    health check
"""
import asyncio
import json
import mimetypes
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from transcript_editor.editor import (
    checkout,
    load_metadata,
    get_source_media_path,
    _get_all_words,
    _get_aligned_words_and_status,
    render as editor_render,
    retranscribe as editor_retranscribe,
)

app = FastAPI(title="Transcript Editor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _segments_from_metadata(metadata: dict) -> list[dict]:
    segments = []
    for seg in metadata.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        segments.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": text,
        })
    return segments


@app.get("/status")
def status():
    return {"status": "ok"}


@app.get("/session")
def session(metadata: str = Query(...)):
    if not os.path.isabs(metadata):
        raise HTTPException(400, "metadata must be an absolute path")
    if not os.path.exists(metadata):
        raise HTTPException(404, f"Not found: {metadata}")

    meta = load_metadata(metadata)
    media_path = get_source_media_path(metadata, meta)

    base_dir = os.path.dirname(metadata)
    base_name = os.path.basename(metadata).replace("-metadata.json", "")
    edit_path = os.path.join(base_dir, f"{base_name}-transcript.edit.md")

    if not os.path.exists(edit_path):
        edit_path = checkout(metadata)

    with open(edit_path) as f:
        edit_text = "".join(
            line for line in f if not line.strip().startswith("#")
        ).strip()

    return {
        "metadata_path": metadata,
        "edit_path": edit_path,
        "edit_text": edit_text,
        "segments": _segments_from_metadata(meta),
        "media_path": media_path,
    }


class DiffRequest(BaseModel):
    metadata_path: str
    edit_text: str


@app.post("/diff")
def diff(req: DiffRequest):
    if not os.path.exists(req.metadata_path):
        raise HTTPException(404, f"Not found: {req.metadata_path}")

    meta = load_metadata(req.metadata_path)
    original_words = _get_all_words(meta)
    if not original_words:
        raise HTTPException(400, "No words found in metadata")

    aligned = _get_aligned_words_and_status(original_words, req.edit_text)

    kept = [w for w, s in aligned if s == "KEEP"]
    removed = [w for w, s in aligned if s == "REMOVE"]

    total_dur = (
        original_words[-1]["end"] - original_words[0]["start"]
        if original_words
        else 0
    )
    time_saved = sum(w["end"] - w["start"] for w in removed)
    time_saved_pct = (100 * time_saved / total_dur) if total_dur > 0 else 0

    return {
        "aligned_words": [
            {
                "word": w["word"].strip(),
                "start": w["start"],
                "end": w["end"],
                "status": s,
            }
            for w, s in aligned
        ],
        "kept_count": len(kept),
        "removed_count": len(removed),
        "time_saved": round(time_saved, 2),
        "time_saved_pct": round(time_saved_pct, 1),
    }


class RenderRequest(BaseModel):
    metadata_path: str
    edit_text: str
    padding: float = 0.1


@app.post("/render")
async def render(req: RenderRequest):
    if not os.path.exists(req.metadata_path):
        raise HTTPException(404, f"Not found: {req.metadata_path}")

    async def _sse():
        base_dir = os.path.dirname(req.metadata_path)
        base_name = os.path.basename(req.metadata_path).replace("-metadata.json", "")
        edit_path = os.path.join(base_dir, f"{base_name}-transcript.edit.md")

        yield f"data: {json.dumps({'type': 'progress', 'message': 'Writing edit file…'})}\n\n"
        with open(edit_path, "w") as f:
            f.write("# Transcript Edit File\n")
            f.write(req.edit_text + "\n")

        yield f"data: {json.dumps({'type': 'progress', 'message': 'Rendering with ffmpeg…'})}\n\n"
        try:
            output_path = await asyncio.to_thread(
                editor_render,
                req.metadata_path,
                edit_path=edit_path,
                padding=req.padding,
            )
            yield f"data: {json.dumps({'type': 'done', 'output_path': output_path})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


class RetranscribeRequest(BaseModel):
    metadata_path: str


@app.post("/retranscribe")
async def retranscribe(req: RetranscribeRequest):
    if not os.path.exists(req.metadata_path):
        raise HTTPException(404, f"Not found: {req.metadata_path}")

    meta = load_metadata(req.metadata_path)
    source = get_source_media_path(req.metadata_path, meta)
    if source is None:
        raise HTTPException(404, "Source media not found")

    base_dir = os.path.dirname(req.metadata_path)
    base_name = os.path.basename(req.metadata_path).replace("-metadata.json", "")
    source_ext = os.path.splitext(source)[1]
    edited_path = os.path.join(base_dir, f"{base_name}-edited{source_ext}")

    if not os.path.exists(edited_path):
        raise HTTPException(
            404, f"Edited file not found: {edited_path} — run render first"
        )

    async def _sse():
        yield f"data: {json.dumps({'type': 'progress', 'message': 'Starting ASR transcription…'})}\n\n"
        try:
            result = await asyncio.to_thread(editor_retranscribe, edited_path)
            yield f"data: {json.dumps({'type': 'done', 'metadata_path': result})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


@app.get("/media")
def media(path: str = Query(...)):
    if not os.path.isabs(path):
        raise HTTPException(400, "path must be absolute")
    if not os.path.exists(path):
        raise HTTPException(404, f"Not found: {path}")

    mime, _ = mimetypes.guess_type(path)
    return FileResponse(path, media_type=mime or "application/octet-stream")
