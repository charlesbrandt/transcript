import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from transcript_editor import transcriber  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
GOOD = {"text": "hello", "segments": [{"text": " hello", "start": 0.0, "end": 1.0}]}
EMPTY = {"language": "en", "segments": [], "text": ""}


@pytest.fixture(autouse=True)
def asr_env(monkeypatch):
    monkeypatch.setenv("ASR_API_BASE", "http://asr.invalid")
    monkeypatch.delenv("DIARIZE_API_BASE", raising=False)


def _media(tmp_path, name="a.m4a"):
    p = tmp_path / name
    p.write_bytes(b"fake")
    return str(p)


def test_empty_response_writes_no_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "_transcribe_single_chunk", lambda p: dict(EMPTY))
    f = _media(tmp_path)
    transcriber.upload_file(f)
    assert sorted(os.listdir(tmp_path)) == ["a.m4a"]


def test_empty_response_with_delete_blank_routes_to_blanks(tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "_transcribe_single_chunk", lambda p: dict(EMPTY))
    f = _media(tmp_path)
    transcriber.upload_file(f, delete_blank=True)
    assert not os.path.exists(f)
    assert (tmp_path / "blanks" / "a-metadata.json").exists()
    assert not (tmp_path / "a-metadata.json").exists()


def test_good_response_writes_sidecars(tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "_transcribe_single_chunk", lambda p: json.loads(json.dumps(GOOD)))
    f = _media(tmp_path)
    transcriber.upload_file(f)
    assert json.loads((tmp_path / "a-metadata.json").read_text())["text"] == "hello"
    assert (tmp_path / "a-transcript.md").read_text() == "hello\n"


def test_existing_empty_sidecar_counts_as_absent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(transcriber, "_transcribe_single_chunk",
                        lambda p: calls.append(p) or json.loads(json.dumps(GOOD)))
    f = _media(tmp_path)
    (tmp_path / "a-metadata.json").write_text(json.dumps(EMPTY))
    transcriber.upload_file(f)  # update=False: would skip if the empty sidecar counted
    assert len(calls) == 1
    assert json.loads((tmp_path / "a-metadata.json").read_text())["segments"]


def test_existing_good_sidecar_is_skipped(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(transcriber, "_transcribe_single_chunk", lambda p: calls.append(p) or dict(GOOD))
    f = _media(tmp_path)
    (tmp_path / "a-metadata.json").write_text(json.dumps(GOOD))
    transcriber.upload_file(f)
    assert calls == []


def _tone_m4a(path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "aac", "-f", "mp4", str(path)], check=True)


@needs_ffmpeg
def test_single_chunk_uploads_wav_for_m4a(tmp_path, monkeypatch):
    f = tmp_path / "a.m4a"
    _tone_m4a(f)
    seen = {}

    def fake_post(path, *a, **k):
        seen["path"] = path
        seen["head"] = Path(path).read_bytes()[:4]
        return dict(GOOD)
    monkeypatch.setattr(transcriber, "_post_to_asr", fake_post)
    assert transcriber._transcribe_single_chunk(str(f)) == GOOD
    assert seen["path"].endswith(".wav") and seen["head"] == b"RIFF"
    assert not os.path.exists(seen["path"])  # temp wav cleaned up


def test_single_chunk_passes_other_formats_through(tmp_path, monkeypatch):
    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(transcriber, "_post_to_asr", lambda p, *a, **k: seen.append(p) or dict(GOOD))
    transcriber._transcribe_single_chunk(str(f))
    assert seen == [str(f)]


def test_single_chunk_falls_back_when_ffmpeg_fails(tmp_path, monkeypatch):
    f = tmp_path / "a.m4a"
    f.write_bytes(b"not really mp4")
    seen = []
    monkeypatch.setattr(transcriber, "_post_to_asr", lambda p, *a, **k: seen.append(p) or dict(GOOD))
    transcriber._transcribe_single_chunk(str(f))
    assert seen == [str(f)]
