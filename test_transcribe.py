import requests
import json
import subprocess
import sys

# Extract a clip from the middle
src = sys.argv[1]
subprocess.run([
    "ffmpeg", "-y", "-i", src,
    "-ss", "90", "-t", "20",
    "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
    "/tmp/clip.wav"
], check=True, capture_output=True)

with open("/tmp/clip.wav", "rb") as f:
    data = f.read()

resp = requests.post(
    "http://192.168.2.99:9000/asr",
    params={"encode": "true", "task": "transcribe", "language": "en", "output": "json"},
    files={"audio_file": ("clip.wav", data, "application/octet-stream")},
    timeout=120
)
body = resp.json()
print(json.dumps(body, indent=2)[:2000])
