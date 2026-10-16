"""
Tests for transcript_editor.diarization using synthetic words and turns (no network).
Run with: python -m pytest test_diarization.py   (or: python test_diarization.py)
"""
from unittest import mock

from transcript_editor import diarization


def w(start, end, word="x"):
    return {"start": start, "end": end, "word": word}


def seg(*words):
    return {"start": words[0]["start"], "end": words[-1]["end"], "text": "x", "words": list(words)}


def test_assign_speaker_max_overlap():
    turns = [
        {"start": 0.0, "end": 1.2, "speaker": "SPEAKER_01"},
        {"start": 1.2, "end": 5.0, "speaker": "SPEAKER_00"},
    ]
    # word straddles the boundary but mostly sits in the second turn
    assert diarization.assign_speaker(w(1.0, 2.0), turns) == "SPEAKER_00"
    assert diarization.assign_speaker(w(0.0, 1.0), turns) == "SPEAKER_01"


def test_assign_speaker_nearest_fallback():
    turns = [
        {"start": 0.0, "end": 1.0, "speaker": "S0"},
        {"start": 5.0, "end": 6.0, "speaker": "S1"},
    ]
    assert diarization.assign_speaker(w(1.2, 1.4), turns) == "S0"
    assert diarization.assign_speaker(w(4.5, 4.7), turns) == "S1"
    assert diarization.assign_speaker(w(1.0, 2.0), []) is None


def test_labels_ordered_by_first_appearance():
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_07"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_02"},
        {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_07"},
    ]
    segments = [seg(w(0.1, 0.5), w(0.6, 1.0)), seg(w(2.1, 2.5)), seg(w(4.1, 4.5))]
    assert diarization.apply_speakers(segments, turns) == 2
    assert [s["speaker"] for s in segments] == ["A", "B", "A"]
    assert segments[1]["words"][0]["speaker"] == "B"


def test_segment_speaker_is_majority_of_words():
    turns = [
        {"start": 0.0, "end": 1.0, "speaker": "X"},
        {"start": 1.0, "end": 4.0, "speaker": "Y"},
    ]
    segments = [seg(w(0.2, 0.8), w(1.1, 1.5), w(1.6, 2.0))]
    diarization.apply_speakers(segments, turns)
    assert [x["speaker"] for x in segments[0]["words"]] == ["A", "B", "B"]
    assert segments[0]["speaker"] == "B"


def test_segment_without_words_uses_its_own_timing():
    turns = [{"start": 0.0, "end": 5.0, "speaker": "X"}]
    segments = [{"start": 1.0, "end": 2.0, "text": "hi", "words": None}]
    diarization.apply_speakers(segments, turns)
    assert segments[0]["speaker"] == "A"


def test_no_turns_leaves_segments_untouched():
    segments = [seg(w(0.0, 1.0))]
    assert diarization.apply_speakers(segments, []) == 0
    assert "speaker" not in segments[0] and "speaker" not in segments[0]["words"][0]


def test_many_speakers_get_distinct_labels():
    turns = [{"start": i, "end": i + 1, "speaker": f"S{i}"} for i in range(28)]
    segments = [seg(w(i + 0.1, i + 0.9)) for i in range(28)]
    assert diarization.apply_speakers(segments, turns) == 28
    labels = [s["speaker"] for s in segments]
    assert len(set(labels)) == 28 and labels[0] == "A" and labels[25] == "Z"


def test_unreachable_sidecar_never_raises():
    segments = [seg(w(0.0, 1.0))]
    def fake_extract(src, dest):
        open(dest, "wb").close()

    with mock.patch.object(diarization, "_extract_audio", side_effect=fake_extract), \
         mock.patch.object(diarization.requests, "post", side_effect=diarization.requests.exceptions.ConnectionError("down")):
        assert diarization.diarize_segments("/tmp/x.wav", segments, diarize_base="http://127.0.0.1:1") == 0
    assert "speaker" not in segments[0]


def test_missing_base_url_never_raises():
    segments = [seg(w(0.0, 1.0))]
    with mock.patch.dict("os.environ", {}, clear=True):
        assert diarization.diarize_segments("/tmp/x.wav", segments) == 0


def test_speaker_transcript_joins_consecutive_turns():
    segments = [
        {"start": 2.0, "end": 3.0, "text": " Hey, Charles.", "speaker": "A"},
        {"start": 4.0, "end": 5.0, "text": "Hey.", "speaker": "B"},
        {"start": 5.0, "end": 6.0, "text": "Good afternoon. ", "speaker": "B"},
        {"start": 3725.0, "end": 3726.0, "text": "Bye.", "speaker": "A"},
    ]
    assert diarization.speaker_transcript(segments) == (
        "**A** (00:00:02): Hey, Charles.\n\n"
        "**B** (00:00:04): Hey. Good afternoon.\n\n"
        "**A** (01:02:05): Bye.\n"
    )


def test_speaker_transcript_without_speakers_writes_nothing():
    import os, tempfile
    path = os.path.join(tempfile.mkdtemp(), "x-transcript-speakers.md")
    assert diarization.speaker_transcript([{"start": 0, "end": 1, "text": "hi"}]) == ""
    assert diarization.write_speaker_transcript([{"start": 0, "end": 1, "text": "hi"}], path) is False
    assert not os.path.exists(path)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
