"""
Optional speaker diarization for transcripts.

The whole file is diarized once by a pyannote sidecar (POST {DIARIZE_API_BASE}/diarize),
then each word of the stitched, offset-corrected transcript is given the speaker whose
turn overlaps it the most. Generic labels (A, B, C, ...) are assigned in order of first
appearance. Any failure is logged and results in no speakers, never an exception.
"""

import logging
import os
import string
import subprocess
import tempfile

import requests


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speaker(item, turns):
    """
    Returns the raw speaker of the turn with the largest time overlap with item
    (a dict with 'start' and 'end'). Falls back to the nearest turn when nothing overlaps.
    Returns None if there are no turns.
    """
    if not turns:
        return None
    best, best_overlap = None, 0.0
    for turn in turns:
        overlap = _overlap(item["start"], item["end"], turn["start"], turn["end"])
        if overlap > best_overlap:
            best, best_overlap = turn["speaker"], overlap
    if best is not None:
        return best
    mid = (item["start"] + item["end"]) / 2
    nearest = min(
        turns,
        key=lambda t: 0 if t["start"] <= mid <= t["end"] else min(abs(mid - t["start"]), abs(mid - t["end"])),
    )
    return nearest["speaker"]


def _label(index):
    letters = string.ascii_uppercase
    return letters[index] if index < len(letters) else f"S{index + 1}"


def apply_speakers(segments, turns):
    """
    Adds a 'speaker' key to every word and segment in segments (in place).
    Labels are A, B, C, ... ordered by first appearance in the transcript.
    A segment's speaker is the majority speaker of its words (ties go to the
    speaker that appears first); a segment without words is assigned by its own timing.
    Returns the number of distinct speakers labelled (0 if turns is empty).
    """
    if not turns:
        return 0

    labels = {}

    def label_for(raw):
        if raw not in labels:
            labels[raw] = _label(len(labels))
        return labels[raw]

    for segment in sorted(segments, key=lambda s: s.get("start", 0)):
        counts = {}
        for word in segment.get("words") or []:
            if "start" not in word or "end" not in word:
                continue
            word["speaker"] = label_for(assign_speaker(word, turns))
            counts[word["speaker"]] = counts.get(word["speaker"], 0) + 1
        if counts:
            # max() returns the first maximal key; dict order is first appearance
            segment["speaker"] = max(counts, key=counts.get)
        elif "start" in segment and "end" in segment:
            segment["speaker"] = label_for(assign_speaker(segment, turns))
    return len(labels)


def _extract_audio(file_path, output_path):
    """Extracts the first audio stream as 16 kHz mono WAV so we upload audio, not a video."""
    cmd = [
        "ffmpeg", "-y", "-i", file_path,
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def fetch_turns(file_path, diarize_base=None, min_speakers=None, max_speakers=None, timeout=1800):
    """
    Diarizes the whole file via the sidecar and returns a list of
    {"start", "end", "speaker"} turns, or None on any failure (a warning is logged).
    """
    diarize_base = diarize_base or os.getenv("DIARIZE_API_BASE")
    if not diarize_base:
        logging.warning("Diarization requested but DIARIZE_API_BASE is not set. Continuing without speakers.")
        return None

    params = {}
    if min_speakers:
        params["min_speakers"] = min_speakers
    if max_speakers:
        params["max_speakers"] = max_speakers

    temp_dir = tempfile.mkdtemp(prefix="diarize_")
    try:
        wav_path = os.path.join(temp_dir, "audio.wav")
        _extract_audio(file_path, wav_path)
        logging.info(f"Diarizing {file_path} via {diarize_base}/diarize")
        with open(wav_path, "rb") as fileb:
            response = requests.post(
                f"{diarize_base.rstrip('/')}/diarize", params=params, files={"audio_file": fileb}, timeout=timeout
            )
        response.raise_for_status()
        result = response.json()
        # exclusive turns never overlap, which is what we want for word assignment
        turns = result.get("exclusive_turns") or result.get("turns") or []
        if not turns:
            logging.warning(f"Diarization returned no speaker turns for {file_path}. Continuing without speakers.")
            return None
        logging.info(f"Diarization found {len(result.get('speakers', []))} speakers in {len(turns)} turns")
        return turns
    except subprocess.CalledProcessError as e:
        logging.warning(f"Diarization skipped, could not extract audio from {file_path}: {e.stderr}")
    except (requests.exceptions.RequestException, OSError, ValueError, KeyError) as e:
        logging.warning(f"Diarization failed for {file_path}, continuing without speakers: {e}")
    finally:
        for name in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, name))
        os.rmdir(temp_dir)
    return None


def diarize_segments(file_path, segments, diarize_base=None, min_speakers=None, max_speakers=None):
    """
    Diarizes file_path once and adds 'speaker' to segments and their words (in place).
    Never raises: on any failure the segments are left untouched.
    Returns the number of speakers labelled.
    """
    try:
        turns = fetch_turns(file_path, diarize_base, min_speakers, max_speakers)
        if not turns:
            return 0
        return apply_speakers(segments, turns)
    except Exception as e:
        logging.warning(f"Diarization failed for {file_path}, continuing without speakers: {e}")
        return 0
