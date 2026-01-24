# Transcript Editor

A toolkit for transcribing audio/video files and editing them based on their transcripts.

## Features

- **Transcribe** audio and video files using a remote ASR (Automatic Speech Recognition) API
- **Edit** media by simply editing the transcript text
- **Preview** changes before committing with a visual diff
- **Render** new, trimmed media files with configurable padding
- **Works with any media format** supported by ffmpeg (audio and video)

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set the `ASR_API_BASE` environment variable to point to your transcription API:
   ```bash
   export ASR_API_BASE="http://your-asr-api:9000"
   ```

## ASR Web Service Setup

This toolkit requires a connection to a `whisper-asr-webservice` (https://github.com/ahmetoner/whisper-asr-webservice) instance for transcription. You can either connect to a remote service or run one locally using the provided Docker Compose configuration.

### Connecting to a Remote ASR Service

By default, the application is configured to use a remote ASR service. To connect to it, create a `.env` file in the root of the project and add the following line, replacing the URL with the address of your service:

```
ASR_API_BASE=http://your-remote-asr-service:9000
```

### Running the ASR Service Locally (with Docker)

If you have a compatible GPU, you can run the ASR service locally. The `docker-compose.yml` file includes a pre-configured `whisper` service using a public, pre-built image.

1.  **Enable the Service**: Uncomment the `whisper` service and the `cache-whisper` volume in the `docker-compose.yml` file.

2.  **Configure the Model**: You can adjust the `ASR_MODEL` and `ASR_ENGINE` in the `environment` section of the `whisper` service. The default is the `medium` model with `whisperx`.

3.  **Hugging Face Token**: If you are using a gated model, you will need to provide your Hugging Face token for the `HF_TOKEN` environment variable.

4.  **Update Environment**: Change your `.env` file to point to the local service:
    ```
    ASR_API_BASE=http://localhost:9000
    ```

5.  **Start Services**: Launch the services using Docker Compose:
    ```bash
    docker compose up -d --build
    ```

For more details on configuring the ASR service, refer to the [official whisper-asr-webservice documentation](https://ahmetoner.github.io/whisper-asr-webservice).

## Usage

All-in-one-go option: 

```bash
python transcript.py path/to/audio.wav
```

### 1. Transcribe a Media File

```bash
# Transcribe a single file
python -m transcript_editor.transcriber -f path/to/audio.wav

# Transcribe all files in a directory
python -m transcript_editor.transcriber -p path/to/directory/

# Enable splitting for large files
python -m transcript_editor.transcriber -f path/to/long_audio.wav --enable-splitting --chunk-duration 30
```

This creates two files:
- `audio-metadata.json` - Full transcript with word-level timestamps
- `audio-transcript.md` - Human-readable transcript

### 2. Edit the Transcript

Use the editor to create an editable copy of the transcript:

```bash
python transcript_editor/editor.py checkout -m path/to/audio-metadata.json
```

This creates `audio-transcript.edit.md`. Open this file and **delete any lines you want to remove** from the final media.

### 3. Preview Changes

Before rendering, preview what will be cut:

```bash
docker compose exec app python transcript_editor/editor.py diff -m path/to/audio-original-metadata.json
python transcript_editor/editor.py diff -m path/to/audio-metadata.json
```

This shows:
- Which segments will be kept
- Which segments will be removed
- Time savings

### 4. Render the Edited Media

Create a new, trimmed media file:

```bash
# Render with default padding (0.1 seconds)
python transcript_editor/editor.py render -m path/to/audio-metadata.json

# Render with custom padding
python transcript_editor/editor.py render -m path/to/audio-metadata.json --padding 0.25

# Preview the ffmpeg command without executing
python transcript_editor/editor.py render -m path/to/audio-metadata.json --dry-run

# Specify custom output path
python transcript_editor/editor.py render -m path/to/audio-metadata.json -o path/to/output.wav
```

### 5. Retranscribe the Edited File (Optional)

After rendering, you can generate a fresh transcript with accurate timestamps for the new file:

```bash
python transcript_editor/editor.py retranscribe -f path/to/audio-edited.wav
```

## Transcription Details

To handle large audio files and improve transcription accuracy, especially with models like Whisper, audio files are automatically split into smaller 30-second chunks locally before being sent to the ASR API. These chunks are converted to a WAV format (PCM signed 16-bit little-endian, 16 kHz sample rate, mono) to ensure compatibility with the ASR API. The chunking process uses a temporary directory to avoid cluttering your local filesystem, and these temporary files are removed after transcription is complete.

## Command Reference

### `checkout`
Create an editable transcript file.

```bash
python transcript_editor/editor.py checkout -m <metadata.json>
```

### `diff`
Compare edited transcript with original and show what will be removed.

```bash
python transcript_editor/editor.py diff -m <metadata.json> [-e <edit-file.md>]
```

### `render`
Render a new media file with only the kept segments.

```bash
python transcript_editor/editor.py render -m <metadata.json> [options]
```

Options:
- `-e, --edit`: Path to edited transcript (auto-detected if not provided)
- `-o, --output`: Output file path (auto-generated if not provided)
- `-p, --padding`: Seconds of padding around each segment (default: 0.1)
- `--dry-run`: Print ffmpeg command without executing

### `retranscribe`
Regenerate transcript for a media file.

```bash
python transcript_editor/editor.py retranscribe -f <media-file> [options]
```

Options:
- `--enable-splitting`: Enable chunking for large files (default: True)
- `--chunk-duration`: Chunk duration in seconds (default: 30)

## Example Workflow

```bash
# 1. Transcribe original file
python -m transcript_editor.transcriber -f recording.mp4 --enable-splitting

# 2. Create editable transcript
python transcript_editor/editor.py checkout -m recording-metadata.json

# 3. Edit recording-transcript.edit.md (delete unwanted lines)

# 4. Preview changes
python transcript_editor/editor.py diff -m recording-metadata.json

# 5. Render edited version with 0.2s padding
python transcript_editor/editor.py render -m recording-metadata.json -p 0.2

# 6. Optionally retranscribe the edited file
python transcript_editor/editor.py retranscribe -f recording-edited.mp4
```

## File Structure

```
your-media-directory/
├── recording.mp4              # Original media file
├── recording-metadata.json    # Transcript metadata (timestamps, words)
├── recording-transcript.md    # Human-readable transcript
├── recording-transcript.edit.md  # Editable transcript (created by checkout)
└── recording-edited.mp4       # Edited media file (created by render)
```

## Tips

- **Padding**: Use larger padding values (0.2-0.5s) for more natural-sounding cuts
- **Video**: The tool automatically handles video files, preserving both video and audio streams
- **Large files**: Use `--enable-splitting` for files longer than 30 seconds for better transcription accuracy
- **Iterative editing**: You can run checkout/diff/render multiple times to refine your edits