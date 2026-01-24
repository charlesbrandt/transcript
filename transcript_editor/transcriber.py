#!/usr/bin/env python3

"""
A script to transcribe audio files using a remote ASR (Automatic Speech Recognition) API.
It supports uploading individual files or processing directories, saving transcripts and metadata.
"""

import argparse
import os
import requests
import json
import logging
import subprocess
import tempfile
import shutil
import time # Added
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter # Added
from urllib3.util.retry import Retry # Added

load_dotenv()

def get_media_duration(file_path):
    """
    Gets the duration of a media file using ffprobe.
    Returns duration in seconds (float).
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        logging.info(f"Duration of {file_path}: {duration} seconds")
        return duration
    except subprocess.CalledProcessError as e:
        logging.error(f"Error getting duration for {file_path}: {e.stderr}")
        return None
    except ValueError:
        logging.error(f"Could not parse duration for {file_path}: {result.stdout}")
        return None


def current_session(parent_directory):
    session = datetime.now().strftime("%Y%m%d")
    #expand parent_directory path to resolve ~/
    parent_directory = os.path.expanduser(parent_directory)
    session_dir = os.path.join(parent_directory, session)
    os.makedirs(session_dir, exist_ok=True)

    return session, session_dir

SUPPORTED_AUDIO_EXTENSIONS = [".flac", ".mp4", ".mp3", ".m4a", ".wav", ".webm", ".ogg", ".avi", ".mov", ".MOV", "f4v", ".mkv", ".aac"]

def split_media(file_path, chunk_duration, output_dir):
    """
    Splits a media file into chunks of specified duration using ffmpeg.
    Extracts audio and converts to WAV format for ASR API compatibility.
    Returns a list of paths to the generated chunk files.
    """
    os.makedirs(output_dir, exist_ok=True)
    base_name = Path(file_path).stem
    output_pattern = os.path.join(output_dir, f"{base_name}_chunk_%04d.wav")

    try:
        cmd = [
            "ffmpeg",
            "-i", file_path,
            "-f", "segment",
            "-segment_time", str(chunk_duration),
            "-c:a", "pcm_s16le",  # Audio codec: PCM signed 16-bit little-endian
            "-ar", "16000",      # Audio sample rate: 16 kHz (common for ASR)
            "-ac", "1",          # Audio channels: mono
            "-map", "0:a:0",     # Map only the first audio stream
            "-vn",               # No video
            output_pattern,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        logging.info(f"Successfully split {file_path} into chunks in {output_dir}")

        # Get list of generated chunk files
        chunk_files = sorted([
            os.path.join(output_dir, f) for f in os.listdir(output_dir)
            if f.startswith(f"{base_name}_chunk_") and f.endswith(".wav")
        ])
        return chunk_files
    except subprocess.CalledProcessError as e:
        logging.error(f"Error splitting media file {file_path}: {e.stderr}")
        return []

def _get_next_backup_path(directory, base_filename_no_ext, extension):
    """
    Determines the next available backup path for a given file.
    e.g., file.json -> file.json.1, file.json.1 -> file.json.2
    """
    base_name = f"{base_filename_no_ext}{extension}"
    existing_backups = sorted([
        f for f in os.listdir(directory)
        if f.startswith(base_name) and f != base_name
    ])

    next_version = 1
    if existing_backups:
        last_backup = existing_backups[-1]
        try:
            # Extract version number from the last backup file name
            # e.g., "file.json.1" -> 1
            parts = last_backup.split('.')
            if len(parts) > 2 and parts[-1].isdigit():
                next_version = int(parts[-1]) + 1
            else:
                # Fallback if naming convention is unexpected
                next_version = len(existing_backups) + 1
        except ValueError:
            next_version = len(existing_backups) + 1

    return os.path.join(directory, f"{base_filename_no_ext}{extension}.{next_version}")

def check_asr_api_health(asr_base=None, timeout=5):
    """
    Check if the ASR API is available.
    Returns True if the API is available, False otherwise.
    """
    if not asr_base:
        asr_base = os.getenv("ASR_API_BASE")
        if not asr_base:
            logging.error("ASR_API_BASE is not set in the environment variables.")
            return False
        
    try:
        # Try to connect to the ASR API
        response = requests.get(f"{asr_base}/health", timeout=timeout)
        
        # If the /health endpoint doesn't exist, try the base URL
        if response.status_code == 404:
            response = requests.get(asr_base, timeout=timeout)
        
        if response.status_code < 400:
            logging.info(f"health of ASR API at: {asr_base}: available")
            return True
        else:
            logging.error(f"health of ASR API at: {asr_base}: returned status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"health of ASR API at: {asr_base}: Failed to connect: {e}")
        return False

def _transcribe_single_chunk(file_path, max_retries=3, backoff_factor=0.5):
    """Internal function to upload a single chunk to the ASR API with retries."""
    asr_base = os.getenv("ASR_API_BASE")
    if not asr_base:
        raise ValueError("ASR_API_BASE is not set in the environment variables.")
    
    # Check if ASR API is available before attempting to transcribe
    check_asr_api_health(asr_base)
    
    url = f"{asr_base}/asr/"

    params = {
        "encode": "true",
        "task": "transcribe",
        "language": "en",
        "word_timestamps": "true",
        "output": "json"
    }
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504], # Status codes to retry on
        allowed_methods=["POST"] # Methods to retry on
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        with open(file_path, "rb") as fileb:
            files = {"audio_file": fileb}
            # Use the session for the request
            response = session.post(url, params=params, files=files, timeout=60) # Added timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {file_path} after {max_retries} retries: {e}")
        return {"text": "", "segments": []}
    except requests.exceptions.JSONDecodeError: # Changed from requests.exceptions.JSONDecodeError
        logging.error(f"Response is not in JSON format for {file_path}: {response.text if 'response' in locals() else 'No response object'}")
        return {"text": "", "segments": []}
    finally:
        session.close()


def upload_file(file_path, update=False, delete_blank=False, enable_splitting=True, chunk_duration=30, chunk_delay_seconds=0.0):
    asr_base = os.getenv("ASR_API_BASE")
    if not asr_base:
        raise ValueError("ASR_API_BASE is not set in the environment variables.")
    url = f"{asr_base}/asr/"
    logging.info(f"Sending request to: {url}")
    logging.info(f"Processing file: {file_path}")

    source_path = os.path.dirname(file_path)
    source_basename = os.path.basename(file_path)
    source_basename_no_ext = os.path.splitext(source_basename)[0]

    # Save the json file in the same directory as the source file
    json_filename = f"{source_basename_no_ext}-metadata.json"
    json_path = os.path.join(source_path, json_filename)
    md_filename = f"{source_basename_no_ext}-transcript.md"
    md_path = os.path.join(source_path, md_filename)
    if len(json_path) > 255:  
        # If the path is too long, truncate it
        json_path = os.path.join(source_path, f"{source_basename_no_ext[0:230]}-metadata.json")
        logging.warning(f"JSON Path too long, using shortened path: {json_path}")
    if len(md_path) > 255:
        # If the path is too long, truncate it
        md_path = os.path.join(source_path, f"{source_basename_no_ext[0:230]}-transcript.md")
        logging.warning(f"Markdown Path too long, using shortened path: {md_path}")

    if os.path.exists(json_path) and not update:
        logging.info(f"Metadata file already exists: {json_path}. Skipping.")
        return
    elif os.path.exists(json_path) and update:
        # Backup existing metadata and transcript files
        backup_json_path = _get_next_backup_path(source_path, source_basename_no_ext, "-metadata.json")
        os.rename(json_path, backup_json_path)
        logging.info(f"Moved existing metadata file to: {backup_json_path}")

        backup_md_path = _get_next_backup_path(source_path, source_basename_no_ext, "-transcript.md")
        os.rename(md_path, backup_md_path)
        logging.info(f"Moved existing transcript file to: {backup_md_path}")

    final_metadata = {}

    if enable_splitting:
        duration = get_media_duration(file_path)
        if duration is None:
            logging.error(f"Could not determine duration for {file_path}. Skipping splitting.")
            enable_splitting = False # Fallback to direct upload if duration cannot be determined
        elif duration > chunk_duration:
            logging.info(f"File duration ({duration:.2f}s) exceeds chunk duration ({chunk_duration}s). Splitting enabled.")
            temp_dir = tempfile.mkdtemp(prefix="audio_chunks_")
            chunk_files = split_media(file_path, chunk_duration, temp_dir)

            all_segments = []
            full_text_parts = []
            cumulative_duration = 0.0

            total_chunks = len(chunk_files) # Get total chunks
            logging.info(f"File {os.path.basename(file_path)} split into {total_chunks} chunks.")
            if total_chunks > 0: # Print only if there are chunks
                print(f"  File {os.path.basename(file_path)} split into {total_chunks} chunks.") # Console output

            for i, chunk_file in enumerate(chunk_files):
                current_chunk_num = i + 1
                # Console output for chunk progress
                print(f"  Transcribing chunk {current_chunk_num}/{total_chunks} for {os.path.basename(file_path)}: {os.path.basename(chunk_file)}")
                logging.info(f"Transcribing chunk {current_chunk_num}/{total_chunks}: {os.path.basename(chunk_file)} for original file {file_path}")
                
                # Add delay before transcribing the next chunk, except for the first one
                # if i > 0:
                #     logging.info(f"Waiting {chunk_delay_seconds}s before next chunk...")
                #     time.sleep(chunk_delay_seconds)
                
                chunk_metadata = _transcribe_single_chunk(chunk_file)

                if "segments" in chunk_metadata:
                    for segment in chunk_metadata["segments"]:
                        # Adjust segment timestamps relative to the original file
                        segment["start"] += cumulative_duration
                        segment["end"] += cumulative_duration
                        
                        # Adjust word timestamps within the segment and filter out words without start/end
                        if "words" in segment:
                            valid_words_for_segment = []
                            for word in segment["words"]:
                                # Only append words that have both 'start' and 'end' for proper timing
                                if "start" in word and "end" in word:
                                    word["start"] += cumulative_duration
                                    word["end"] += cumulative_duration
                                    valid_words_for_segment.append(word)
                                else:
                                    logging.warning(f"Skipping word due to missing 'start' or 'end' keys: {word}")
                            segment["words"] = valid_words_for_segment
                        
                        # Only append segment if it has valid time information and content
                        # Assuming 'start' and 'end' keys are always present for segments as per API response
                        if "start" in segment and "end" in segment and segment.get("text", "").strip():
                            all_segments.append(segment)
                        else:
                            logging.warning(f"Skipping segment due to missing 'start', 'end' or empty text: {segment}")
                
                if "text" in chunk_metadata:
                    full_text_parts.append(chunk_metadata["text"].strip())
                
                # Update cumulative duration based on the actual chunk duration or expected chunk_duration
                # For the last chunk, use its actual duration if available, otherwise use chunk_duration
                if i < len(chunk_files) - 1:
                    cumulative_duration += chunk_duration
                else:
                    # For the last chunk, calculate its actual duration to be precise
                    actual_chunk_duration = get_media_duration(chunk_file)
                    if actual_chunk_duration is not None:
                        cumulative_duration += actual_chunk_duration
                    else:
                        cumulative_duration += chunk_duration # Fallback

                os.remove(chunk_file) # Clean up chunk file after processing

            shutil.rmtree(temp_dir) # Clean up temporary directory

            final_metadata = {
                "text": " ".join(full_text_parts).strip(),
                "segments": all_segments,
                "source_file": os.path.basename(file_path),
                "processed_with_splitting": True,
                "original_duration": duration,
                "chunk_duration_setting": chunk_duration
            }
            logging.info(f"Finished processing all chunks for {file_path}.")
        else:
            logging.info(f"File duration ({duration:.2f}s) is within chunk limit ({chunk_duration}s). Uploading directly.")
            final_metadata = _transcribe_single_chunk(file_path)
    else:
        logging.info(f"Splitting not enabled. Uploading file directly: {file_path}")
        final_metadata = _transcribe_single_chunk(file_path)

    # Ensure 'text' key exists for consistent access
    if "text" not in final_metadata:
        final_metadata["text"] = ""

    if delete_blank and not final_metadata["text"].strip():
        blank_path = os.path.join(source_path, "blanks")
        os.makedirs(blank_path, exist_ok=True)
        json_path = os.path.join(blank_path, json_filename)
        with open(json_path, "w") as f:
            json.dump(final_metadata, f, indent=4)

        logging.info(f"Blank transcription, deleting audio_file {file_path}")
        os.remove(file_path)
    else:
        with open(json_path, "w") as f:
            json.dump(final_metadata, f, indent=4)
        logging.info(f"Saved metadata: {json_path}")

        # Save a markdown version of the transcript for quick reference
        with open(md_path, "w") as f:
            if "segments" in final_metadata:
                for segment in final_metadata["segments"]:
                    f.write(f"{segment['text'].strip()}\n")
            elif final_metadata["text"]:
                f.write(final_metadata["text"].strip() + "\n")
            else:
                logging.warning(f"No segments or text found in metadata for {file_path}")
        logging.info(f"Saved transcript: {md_path}")

    return final_metadata


def transcribe_path(source_path, update=False, delete_blanks=False, enable_splitting=False, chunk_duration=30):
    logging.info(f"Processing in: {source_path}")
    # Convert the input path to a Path object
    path = Path(source_path)
    files = [p for p in path.iterdir() if p.is_file()]

    audio_files = [f for f in files if f.suffix in SUPPORTED_AUDIO_EXTENSIONS]
    audio_files.sort()

    total_files = len(audio_files)
    logging.info(f"Found {total_files} audio files to process in {source_path}.")
    print(f"Found {total_files} audio files to process in {source_path}.") # Console output

    for i, file_obj in enumerate(audio_files):
        current_file_num = i + 1
        file_name = file_obj.name
        # Console output for progress
        print(f"Processing file {current_file_num}/{total_files}: {file_name}")
        logging.info(f"Starting processing for file {current_file_num}/{total_files}: {file_name}")
        upload_file(
            str(file_obj), # upload_file expects a string path
            update=update,
            delete_blank=delete_blanks,
            enable_splitting=enable_splitting,
            chunk_duration=chunk_duration
        )
        logging.info(f"Finished processing for file {current_file_num}/{total_files}: {file_name}")


if __name__ == "__main__":
    # Create an argument parser
    parser = argparse.ArgumentParser(description="Upload a file to the API.")
    parser.add_argument("-f", "--file", type=str, help="source audio file")
    parser.add_argument(
        "-p", "--path", "--dir", type=str, help="source audio directory"
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="force update of existing transcriptions",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="recursively process directories"
    )
    parser.add_argument(
        "-d", "--delete-blanks", action="store_true", help="delete blank files"
    )
    parser.add_argument(
        "--enable-splitting",
        action="store_true",
        help="Enable splitting of large audio files into chunks for processing.",
    )
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=30,
        help="Duration in seconds for audio chunks when splitting is enabled (default: 30).",
    )
    args = parser.parse_args()

    if args.path:
        source_path = args.path
    elif args.file:
        source_path = os.path.dirname(args.file)
    else:
        ar = os.getenv("AUDIO_ROOT")
        today, session_dir = current_session(ar)
        source_path = session_dir
        args.path = source_path

    log_dest = os.path.join(source_path, "processing.log")
    logging.basicConfig(
        filename=log_dest,
        level=logging.INFO,
        format="%(asctime)s: %(levelname)-8s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.file:
        upload_file(
            args.file,
            update=args.update,
            delete_blank=args.delete_blanks,
            enable_splitting=args.enable_splitting,
            chunk_duration=args.chunk_duration,
        )
    elif args.path:
        if args.recursive:
            for root, dirs, files in os.walk(source_path):
                transcribe_path(
                    root,
                    update=args.update,
                    delete_blanks=args.delete_blanks,
                    enable_splitting=args.enable_splitting,
                    chunk_duration=args.chunk_duration,
                )
        else:
            transcribe_path(
                source_path,
                update=args.update,
                delete_blanks=args.delete_blanks,
                enable_splitting=args.enable_splitting,
                chunk_duration=args.chunk_duration,
            )