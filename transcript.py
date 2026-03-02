import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for imports to find transcript_editor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from transcript_editor import transcriber
from transcript_editor import editor

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe an audio file and generate an edited output based on the transcript."
    )
    parser.add_argument("audio_file", type=str, help="Path to the audio file (e.g., path/to/audio.wav)")
    
    args = parser.parse_args()
    
    audio_file_path = os.path.abspath(args.audio_file)
    
    if not os.path.exists(audio_file_path):
        print(f"Error: Audio file not found at {audio_file_path}")
        sys.exit(1)

    print(f"Processing audio file: {audio_file_path}")

    # Step 1: Transcribe the audio file
    print("Step 1/4: Transcribing audio file...")
    # upload_file returns the final_metadata dictionary, but the other functions expect a path
    # So we'll get the metadata path from the audio file path
    transcriber.upload_file(audio_file_path, update=True)
    
    # Construct the expected metadata path
    audio_basename = Path(audio_file_path).stem
    metadata_path = os.path.join(os.path.dirname(audio_file_path), f"{audio_basename}-metadata.json")
    
    if not os.path.exists(metadata_path):
        print(f"Error: Metadata file was not generated at {metadata_path}")
        sys.exit(1)
        
    print(f"Metadata generated at: {metadata_path}")

    # Step 2: Checkout the transcript for editing
    print("Step 2/4: Checking out transcript for editing...")
    edit_file_path = editor.checkout(metadata_path)
    print(f"Editable transcript created at: {edit_file_path}")

    # Step 3: Diff the transcript (no actual edits, so should show no changes)
    print("Step 3/4: Comparing edited transcript with original...")
    editor.diff(metadata_path, edit_file_path)
    print("Diff complete. (Assuming no manual edits, no changes will be shown)")

    # Step 4: Render the new media file
    print("Step 4/4: Rendering new media file...")

    rendered_output_path = editor.render(metadata_path, padding=0.5, edit_path=edit_file_path)
    print(f"New media file rendered at: {rendered_output_path}")

    print(f"\nTo re-run render after editing '{edit_file_path}', use the command:")
    print(f"docker compose exec app python transcript_editor/editor.py render -m \"{metadata_path}\" --padding 0.5 --diff --keep /path/to/your/keep_file.txt")

    print("""
Your keep file should contain lines like:

10.5,15.2
25.0,30.8
""")

    # Extract audio from the video file
    converted_audio_path = Path(rendered_output_path).with_name(f"{Path(rendered_output_path).stem}-converted.wav")
    print(f'ffmpeg -i "{rendered_output_path}" -vn -acodec pcm_s16le -ar 24000 -ac 1 "{converted_audio_path}"')

    print("\nScript finished successfully.")

if __name__ == "__main__":
    main()