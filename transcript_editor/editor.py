#!/usr/bin/env python3

"""
Transcript Editor: A tool for editing media files by manipulating their transcripts.

Workflow:
1. checkout: Create an editable copy of a transcript
2. (manually edit the transcript to remove unwanted segments)
3. diff: Compare the edited transcript to see what will be cut
4. render: Generate a new, compact media file based on the edited transcript
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import difflib
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Default padding (in seconds) to add around each kept segment
DEFAULT_PADDING = 0.1

def _get_all_words(metadata: Dict) -> List[Dict]:
    """Extracts all words with their timings from the metadata."""
    if 'word_segments' in metadata and metadata['word_segments']:
        return metadata['word_segments']
    
    all_words = []
    for segment in metadata.get('segments', []):
        for word_info in segment.get('words', []):
            # Defensive check: Only append words if they have both 'start' and 'end' keys
            if 'start' in word_info and 'end' in word_info:
                all_words.append(word_info)
            else:
                print(f"Warning: Skipping word due to missing 'start' or 'end' keys in editor: {word_info}")
    return all_words

def _get_aligned_words_and_status(original_words_info: List[Dict], edited_text: str) -> List[Tuple[Dict, str]]:
    """
    Compares original words with the edited text and determines the status of each word.
    Returns a list of (word_info, status) tuples, where status is 'KEEP' or 'REMOVE'.
    """
    original_words_text = [w['word'] for w in original_words_info]
    edited_words_text = edited_text.split() # Simple split for now, can be improved with regex tokenization
    
    matcher = difflib.SequenceMatcher(None, original_words_text, edited_words_text)
    
    aligned_words_status = []
    
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == 'equal':
            for i in range(i1, i2):
                aligned_words_status.append((original_words_info[i], 'KEEP'))
        elif opcode == 'delete':
            for i in range(i1, i2):
                aligned_words_status.append((original_words_info[i], 'REMOVE'))
        elif opcode == 'replace':
            # This case is tricky as it means words were changed.
            # For now, we'll mark original words as REMOVE as we don't have timing for new words
            for i in range(i1, i2):
                aligned_words_status.append((original_words_info[i], 'REMOVE'))
        elif opcode == 'insert':
            # Insertions in edited text mean new words.
            # We don't have timing info for these, so we ignore them for media manipulation.
            pass
            
    return aligned_words_status


def load_metadata(metadata_path: str) -> Dict:
    """Load and return the metadata JSON file."""
    with open(metadata_path, 'r') as f:
        return json.load(f)


def get_source_media_path(metadata_path: str, metadata: Dict) -> Optional[str]:
    """
    Determine the source media file path.
    Looks for common media extensions in the same directory as the metadata file.
    """
    base_dir = os.path.dirname(metadata_path)
    base_name = os.path.basename(metadata_path).replace('-metadata.json', '')
    
    # Check if source_file is specified in metadata
    if 'source_file' in metadata:
        source_path = os.path.join(base_dir, metadata['source_file'])
        if os.path.exists(source_path):
            return source_path
    
    # Otherwise, search for media files with the same base name
    media_extensions = ['.wav', '.mp3', '.mp4', '.m4a', '.flac', '.webm', '.ogg', 
                        '.avi', '.mov', '.MOV', '.mkv', '.aac', '.WAV', '.MP3', '.MP4']
    
    for ext in media_extensions:
        candidate = os.path.join(base_dir, base_name + ext)
        if os.path.exists(candidate):
            return candidate
    
    return None



def checkout(metadata_path: str) -> str:
    """
    Create an editable copy of the transcript for manual editing.
    Returns the path to the created edit file.
    """
    metadata = load_metadata(metadata_path)
    
    if 'segments' not in metadata:
        raise ValueError("Metadata file does not contain 'segments' key.")
    
    base_dir = os.path.dirname(metadata_path)
    base_name = os.path.basename(metadata_path).replace('-metadata.json', '')
    edit_path = os.path.join(base_dir, f"{base_name}-transcript.edit.md")
    
    with open(edit_path, 'w') as f:
        f.write("# Transcript Edit File\n")
        f.write("# Delete lines or words you want to remove from the final media.\n")
        f.write("# Save the file when done, then run 'diff' to preview or 'render' to create the new file.\n")
        f.write("#\n")
        f.write(f"# Source: {metadata_path}\n")
        f.write("# " + "=" * 70 + "\n\n")
        
        # Write out words for word-level editing
        all_words = _get_all_words(metadata)
        current_line_length = 0
        for word_info in all_words:
            word = word_info['word'].strip()
            if current_line_length + len(word) + 1 > 80: # Max 80 chars per line
                f.write("\n")
                current_line_length = 0
            f.write(word + " ")
            current_line_length += len(word) + 1
        f.write("\n")
    
    print(f"Created editable transcript: {edit_path}")
    print("Edit this file to delete words or lines, then run 'diff' to preview or 'render' to create the new media file.")
    return edit_path


def diff(metadata_path: str, edit_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Compare the edited transcript with the original at a word level.
    Shows what will be kept and what will be removed.
    Returns (kept_words, removed_words).
    """
    metadata = load_metadata(metadata_path)
    
    if 'segments' not in metadata:
        raise ValueError("Metadata file does not contain 'segments' key.")
    
    if edit_path is None:
        base_dir = os.path.dirname(metadata_path)
        base_name = os.path.basename(metadata_path).replace('-metadata.json', '')
        edit_path = os.path.join(base_dir, f"{base_name}-transcript.edit.md")
    
    if not os.path.exists(edit_path):
        raise FileNotFoundError(f"Edit file not found: {edit_path}. Run 'checkout' first.")
    
    # Get all original words with their timing information
    original_words_info = _get_all_words(metadata)
    
    # Read edited file content (skip comment lines, preserve structure for now)
    with open(edit_path, 'r') as f:
        edited_text_content = ""
        for line in f:
            if not line.strip().startswith('#'):
                edited_text_content += line.strip() + " "
        edited_text_content = edited_text_content.strip()

    if not original_words_info:
        raise ValueError("No words found in metadata for diffing.")

    # Get aligned words and their status (KEEP/REMOVE)
    aligned_words_status = _get_aligned_words_and_status(original_words_info, edited_text_content)
    
    kept_words = [word_info for word_info, status in aligned_words_status if status == 'KEEP']
    removed_words = [word_info for word_info, status in aligned_words_status if status == 'REMOVE']
    
    # Calculate time savings
    total_original_duration = original_words_info[-1]['end'] - original_words_info[0]['start'] if original_words_info else 0
    kept_duration = sum(word['end'] - word['start'] for word in kept_words)
    removed_duration = sum(word['end'] - word['start'] for word in removed_words)
    
    # Print diff
    print("\n" + "=" * 70)
    print("TRANSCRIPT DIFF (Word-level)")
    print("=" * 70)
    
    for word_info, status in aligned_words_status:
        start = word_info['start']
        end = word_info['end']
        duration = end - start
        text = word_info['word'].strip()
        
        status_display = "  KEEP  " if status == 'KEEP' else "- REMOVE"
        print(f"[{status_display}] ({start:.2f}s - {end:.2f}s, {duration:.2f}s) {text}")
    
    print("\n" + "-" * 70)
    print(f"Words to KEEP:   {len(kept_words)}")
    print(f"Words to REMOVE: {len(removed_words)}")
    print(f"Original duration:  {total_original_duration:.2f}s")
    print(f"Kept duration:      {kept_duration:.2f}s")
    time_saved = total_original_duration - kept_duration
    time_saved_percent = (100 * time_saved / total_original_duration) if total_original_duration > 0 else 0
    
    print(f"Time saved:         {time_saved:.2f}s ({time_saved_percent:.1f}%)")
    print("=" * 70 + "\n")
    
    return kept_words, removed_words


def render(
    metadata_path: str, 
    output_path: Optional[str] = None,
    edit_path: Optional[str] = None,
    padding: float = DEFAULT_PADDING,
    dry_run: bool = False,
    show_diff: bool = False,
    convert_to_wav: bool = True
) -> Optional[str]:
    """
    Render a new media file containing only the kept segments.
    
    Args:
        metadata_path: Path to the original metadata JSON file
        output_path: Path for the output file (auto-generated if not provided)
        edit_path: Path to the edited transcript (auto-detected if not provided)
        padding: Seconds of padding to add around each segment
        dry_run: If True, print the ffmpeg command but don't execute it
    
    Returns:
        Path to the created output file, or None if dry_run
    """
    metadata = load_metadata(metadata_path)
    
    if 'segments' not in metadata:
        raise ValueError("Metadata file does not contain 'segments' key.")
    
    # Find source media file
    source_media = get_source_media_path(metadata_path, metadata)
    if source_media is None:
        raise FileNotFoundError("Could not find source media file.")
    
    print(f"Source media: {source_media}")

    if show_diff:
        print("--- Diff before rendering ---")
        diff(metadata_path, edit_path)
        print("-----------------------------")
    
    # Determine edit file path
    if edit_path is None:
        base_dir = os.path.dirname(metadata_path)
        base_name = os.path.basename(metadata_path).replace('-metadata.json', '')
        edit_path = os.path.join(base_dir, f"{base_name}-transcript.edit.md")
    
    if not os.path.exists(edit_path):
        raise FileNotFoundError(f"Edit file not found: {edit_path}. Run 'checkout' first.")
    
    # Get all original words with their timing information
    original_words_info = _get_all_words(metadata)
    
    # Read edited file content (skip comment lines, preserve structure for now)
    with open(edit_path, 'r') as f:
        edited_text_content = ""
        for line in f:
            if not line.strip().startswith('#'):
                edited_text_content += line.strip() + " "
        edited_text_content = edited_text_content.strip()

    if not original_words_info:
        raise ValueError("No words found in metadata for rendering.")

    # Get aligned words and their status (KEEP/REMOVE)
    aligned_words_status = _get_aligned_words_and_status(original_words_info, edited_text_content)
    
    kept_word_infos = [word_info for word_info, status in aligned_words_status if status == 'KEEP']
    
    if not kept_word_infos:
        raise ValueError("No words to keep. The output would be empty.")
    
    # Get media duration for clamping
    media_duration = get_media_duration(source_media)
    
    # Build list of time ranges to keep (with padding) from individual words
    time_ranges = []
    for word_info in kept_word_infos:
        start = max(0, word_info['start'] - padding)
        end = word_info['end'] + padding
        if media_duration:
            end = min(end, media_duration)
        time_ranges.append((start, end))
    
    # Merge overlapping ranges
    time_ranges.sort()
    merged_ranges = []
    for start, end in time_ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            # Overlaps with previous range, merge them
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))
    
    # print(f"\nTime ranges to keep (with {padding}s padding):")
    # for i, (start, end) in enumerate(merged_ranges):
    #     print(f"  [{i+1}] {start:.3f}s - {end:.3f}s ({end-start:.3f}s)")
    
    # Determine output path
    if output_path is None:
        base_dir = os.path.dirname(metadata_path)
        base_name = os.path.basename(metadata_path).replace('-metadata.json', '')
        source_ext = os.path.splitext(source_media)[1]
        output_path = os.path.join(base_dir, f"{base_name}-edited{source_ext}")
    
    # Build ffmpeg command using the concat filter
    # We'll create a complex filter that selects and concatenates the segments
    
    # Check if source has video
    has_video = check_has_video(source_media)
    
    if has_video:
        # Video + Audio: use both video and audio streams
        filter_parts = []
        concat_inputs = []
        
        for i, (start, end) in enumerate(merged_ranges):
            # Ensure duration is positive
            duration_val = end - start
            if duration_val <= 0:
                continue

            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )
            concat_inputs.append(f"[v{i}][a{i}]")
        
        if not filter_parts: # No valid segments to keep
            raise ValueError("No valid time ranges to keep after processing words.")

        filter_complex = ";".join(filter_parts)
        filter_complex += f";{''.join(concat_inputs)}concat=n={len(merged_ranges)}:v=1:a=1[outv][outa]"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", source_media,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            output_path
        ]
    else:
        # Audio only
        filter_parts = []
        concat_inputs = []
        
        for i, (start, end) in enumerate(merged_ranges):
            # Ensure duration is positive
            duration_val = end - start
            if duration_val <= 0:
                continue

            filter_parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )
            concat_inputs.append(f"[a{i}]")

        if not filter_parts: # No valid segments to keep
            raise ValueError("No valid time ranges to keep after processing words.")
            
        filter_complex = ";".join(filter_parts)
        filter_complex += f";{''.join(concat_inputs)}concat=n={len(merged_ranges)}:v=0:a=1[outa]"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", source_media,
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            output_path
        ]
    
    print(f"\nOutput file: {output_path}")
    # print(f"\nffmpeg command:")
    # print(" ".join(cmd))
    
    if dry_run:
        print("\n[DRY RUN] Command not executed.")
        return None
    
    print("\nRendering...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Successfully created: {output_path}")
        
        if convert_to_wav:
            converted_audio_path = Path(output_path).with_name(f"{Path(output_path).stem}-converted.wav")
            wav_cmd = [
                "ffmpeg", "-y",
                "-i", output_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
                str(converted_audio_path)
            ]
            print(f"\nConverting to WAV: {converted_audio_path}")
            try:
                subprocess.run(wav_cmd, capture_output=True, text=True, check=True)
                print(f"Successfully created WAV: {converted_audio_path}")
            except subprocess.CalledProcessError as e:
                print(f"Error converting to WAV with ffmpeg: {e.stderr}")
                # Do not re-raise, allow the main render to complete

        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error running ffmpeg: {e.stderr}")
        raise


def get_media_duration(file_path: str) -> Optional[float]:
    """Get the duration of a media file using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def check_has_video(file_path: str) -> bool:
    """Check if a media file contains a video stream."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip() == "video"
    except subprocess.CalledProcessError:
        return False


def retranscribe(
    media_path: str,
    enable_splitting: bool = True,
    chunk_duration: int = 30
) -> Optional[str]:
    """
    Regenerate transcript and metadata for an edited media file.
    
    Useful after rendering an edited media file to get accurate timestamps.
    
    Args:
        media_path: Path to the media file to transcribe
        enable_splitting: Whether to split large files into chunks
        chunk_duration: Duration in seconds for each chunk if splitting
    
    Returns:
        Path to the generated metadata file, or None on failure
    """
    from transcript_editor.transcriber import upload_file
    import logging
    
    # Set up logging to console for this operation
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s: %(levelname)-8s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    print(f"Retranscribing: {media_path}")
    
    try:
        result = upload_file(
            media_path,
            update=True,  # Force update to regenerate transcript
            enable_splitting=enable_splitting,
            chunk_duration=chunk_duration
        )
        
        if result:
            # Determine the metadata path
            base_dir = os.path.dirname(media_path)
            base_name = os.path.splitext(os.path.basename(media_path))[0]
            metadata_path = os.path.join(base_dir, f"{base_name}-metadata.json")
            print(f"Successfully generated: {metadata_path}")
            return metadata_path
        else:
            print("Transcription returned no result.")
            return None
            
    except Exception as e:
        print(f"Error during retranscription: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Edit media files by manipulating their transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Step 1: Create an editable transcript
  python editor.py checkout -m data/ZOOM0007-metadata.json
  
  # Step 2: Edit the .edit.md file to remove unwanted lines
  
  # Step 3: Preview changes
  python editor.py diff -m data/ZOOM0007-metadata.json
  
  # Step 4: Render the edited media
  python editor.py render -m data/ZOOM0007-metadata.json --padding 0.2
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Checkout command
    checkout_parser = subparsers.add_parser(
        'checkout', 
        help='Create an editable copy of a transcript'
    )
    checkout_parser.add_argument(
        '-m', '--metadata', 
        required=True,
        help='Path to the metadata JSON file'
    )
    
    # Diff command
    diff_parser = subparsers.add_parser(
        'diff',
        help='Compare edited transcript with original'
    )
    diff_parser.add_argument(
        '-m', '--metadata',
        required=True,
        help='Path to the metadata JSON file'
    )
    diff_parser.add_argument(
        '-e', '--edit',
        help='Path to the edited transcript file (auto-detected if not provided)'
    )
    
    # Render command
    render_parser = subparsers.add_parser(
        'render',
        help='Create a new media file with only the kept segments'
    )
    render_parser.add_argument(
        '-m', '--metadata',
        required=True,
        help='Path to the metadata JSON file'
    )
    render_parser.add_argument(
        '-e', '--edit',
        help='Path to the edited transcript file (auto-detected if not provided)'
    )
    render_parser.add_argument(
        '-o', '--output',
        help='Output file path (auto-generated if not provided)'
    )
    render_parser.add_argument(
        '-p', '--padding',
        type=float,
        default=DEFAULT_PADDING,
        help=f'Padding in seconds around each segment (default: {DEFAULT_PADDING})'
    )
    render_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the ffmpeg command without executing it'
    )
    render_parser.add_argument(
        '--diff',
        action='store_true',
        help='Show diff output before rendering'
    )
    render_parser.add_argument(
        '--no-convert-to-wav',
        action='store_true',
        help='Do not automatically convert the rendered audio to a WAV file.'
    )
    
    # Retranscribe command
    retranscribe_parser = subparsers.add_parser(
        'retranscribe',
        help='Regenerate transcript for an edited media file'
    )
    retranscribe_parser.add_argument(
        '-f', '--file',
        required=True,
        help='Path to the media file to transcribe'
    )
    retranscribe_parser.add_argument(
        '--enable-splitting',
        action='store_true',
        default=True,
        help='Enable splitting of large files into chunks (default: True)'
    )
    retranscribe_parser.add_argument(
        '--chunk-duration',
        type=int,
        default=30,
        help='Duration in seconds for each chunk if splitting (default: 30)'
    )
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    try:
        if args.command == 'checkout':
            checkout(args.metadata)
        elif args.command == 'diff':
            diff(args.metadata, args.edit)
        elif args.command == 'render':
            render(
                args.metadata,
                output_path=args.output,
                edit_path=args.edit,
                padding=args.padding,
                dry_run=args.dry_run,
                show_diff=args.diff,
                convert_to_wav=not args.no_convert_to_wav
            )
        elif args.command == 'retranscribe':
            retranscribe(
                args.file,
                enable_splitting=args.enable_splitting,
                chunk_duration=args.chunk_duration
            )
    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()