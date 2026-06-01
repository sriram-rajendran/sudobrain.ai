"""Sarvam AI transcription client with retry logic and chunked audio support."""

import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from sarvamai import SarvamAI
from dotenv import load_dotenv
from tenacity import retry, wait_exponential_jitter, stop_after_attempt, retry_if_exception_type

load_dotenv()

# Sarvam REST API limit: ~30 seconds per request
CHUNK_DURATION_SECONDS = 25  # Leave margin below 30s
CHUNK_OVERLAP_SECONDS = 2    # Overlap for continuity


def get_client() -> SarvamAI:
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError("SARVAM_API_KEY not set. Add it to .env file.")
    return SarvamAI(api_subscription_key=api_key)


@retry(
    wait=wait_exponential_jitter(initial=1, max=60),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    before_sleep=lambda info: print(f"[Sarvam] Retry {info.attempt_number} after error: {info.outcome.exception()}")
)
def _transcribe_single(client: SarvamAI, audio_path: str) -> object:
    """Transcribe + translate a single audio chunk to English with retry logic.

    Uses Sarvam's speech_to_text_translate endpoint so the output is English
    regardless of source language (handles code-mixed Tamil+English cleanly).
    """
    with open(audio_path, "rb") as f:
        return client.speech_to_text.translate(
            file=f,
            model="saaras:v2.5",
        )


def _get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds."""
    info = sf.info(audio_path)
    return info.duration


def _split_audio(audio_path: str, output_dir: str) -> list[str]:
    """Split audio into chunks of CHUNK_DURATION_SECONDS with overlap."""
    audio, sr = sf.read(audio_path)
    total_samples = len(audio)
    chunk_samples = int(CHUNK_DURATION_SECONDS * sr)
    overlap_samples = int(CHUNK_OVERLAP_SECONDS * sr)
    step = chunk_samples - overlap_samples

    chunks = []
    start = 0
    idx = 0

    while start < total_samples:
        end = min(start + chunk_samples, total_samples)
        chunk = audio[start:end]

        chunk_path = os.path.join(output_dir, f"chunk_{idx:03d}.wav")
        sf.write(chunk_path, chunk, sr, subtype="PCM_16")
        chunks.append({
            "path": chunk_path,
            "start_seconds": start / sr,
            "end_seconds": end / sr,
        })

        start += step
        idx += 1

    return chunks


def _merge_chunk_results(chunk_results: list, audio_path: str) -> dict:
    """Merge transcription results from multiple chunks into one unified transcript."""
    transcript_id = str(uuid.uuid4())
    all_segments = []
    full_text_parts = []
    language = "unknown"

    for chunk_info, result in chunk_results:
        offset = chunk_info["start_seconds"]

        if hasattr(result, "transcript") and result.transcript:
            full_text_parts.append(result.transcript)

        if hasattr(result, "language_code") and result.language_code:
            language = result.language_code

        # Build segment with offset-adjusted timestamps
        if hasattr(result, "transcript") and result.transcript:
            segment = {
                "speaker_id": "speaker_0",
                "start_seconds": offset,
                "end_seconds": chunk_info["end_seconds"],
                "text": result.transcript,
                "language": getattr(result, "language_code", "unknown"),
                "words": [],
            }

            if hasattr(result, "timestamps") and result.timestamps:
                ts = result.timestamps
                words = getattr(ts, "words", []) or []
                starts = getattr(ts, "start_time_seconds", []) or []
                ends = getattr(ts, "end_time_seconds", []) or []

                for i, word in enumerate(words):
                    segment["words"].append({
                        "word": word,
                        "start": (starts[i] + offset) if i < len(starts) else 0.0,
                        "end": (ends[i] + offset) if i < len(ends) else 0.0,
                    })

                if ends:
                    segment["end_seconds"] = ends[-1] + offset

            all_segments.append(segment)

    return _build_unified_transcript(
        transcript_id=transcript_id,
        audio_path=audio_path,
        source="voice_note",
        segments=all_segments,
        full_transcript=" ".join(full_text_parts),
        language=language,
    )


def transcribe_short(audio_path: str) -> dict:
    """Transcribe audio using REST API. Auto-chunks if longer than 25 seconds."""
    duration = _get_audio_duration(audio_path)

    if duration <= CHUNK_DURATION_SECONDS:
        client = get_client()
        result = _transcribe_single(client, audio_path)
        return _parse_rest_response(result, audio_path)

    # Long audio — chunk and transcribe each piece
    return _transcribe_chunked(audio_path, source="voice_note")


def transcribe_meeting(audio_path: str, num_speakers: Optional[int] = None) -> dict:
    """Transcribe meeting audio using Batch API with speaker diarization.

    Uses Sarvam Batch API which supports:
    - Speaker diarization (up to 8 speakers)
    - Files up to 60 minutes
    - No chunking needed
    """
    try:
        return _transcribe_batch_with_diarization(audio_path, num_speakers)
    except Exception as e:
        print(f"[Sarvam] Batch API failed: {e}. Falling back to REST API.")
        # Fallback to REST API without diarization
        duration = _get_audio_duration(audio_path)
        if duration <= CHUNK_DURATION_SECONDS:
            client = get_client()
            result = _transcribe_single(client, audio_path)
            return _parse_diarized_response(result, audio_path)
        return _transcribe_chunked(audio_path, source="meeting")


def _transcribe_batch_with_diarization(audio_path: str, num_speakers: Optional[int] = None) -> dict:
    """Use Sarvam Batch API for diarized transcription."""
    client = get_client()

    print(f"[Sarvam] Creating batch job with diarization (speakers: {num_speakers or 'auto'})...")

    # Create batch job
    job_params = {
        "model": "saaras:v2.5",
        "with_diarization": True,
    }
    if num_speakers:
        job_params["num_speakers"] = num_speakers

    job = client.speech_to_text_translate_job.create_job(**job_params)
    print(f"[Sarvam] Job ID: {job.job_id}")

    # Upload audio file
    print("[Sarvam] Uploading audio...")
    job.upload_files(file_paths=[audio_path], timeout=120)

    # Start processing
    print("[Sarvam] Starting batch processing...")
    job.start()

    # Wait for completion
    print("[Sarvam] Waiting for completion...")
    job.wait_until_complete()

    # Download outputs
    output_dir = os.path.join(os.path.dirname(audio_path), "batch_output")
    os.makedirs(output_dir, exist_ok=True)
    job.download_outputs(output_dir=output_dir)

    # Parse the output JSON
    import json as json_mod
    transcript_id = str(uuid.uuid4())
    segments = []
    speaker_ids = set()
    full_transcript = ""
    language = "unknown"

    for filename in os.listdir(output_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(output_dir, filename)
            with open(filepath) as f:
                data = json_mod.load(f)

            full_transcript = data.get("transcript", "")
            language = data.get("language_code", "unknown")

            # Parse diarized transcript
            diarized = data.get("diarized_transcript")
            if diarized and isinstance(diarized, dict):
                entries = diarized.get("entries", [])
                print(f"[Sarvam] Diarization: {len(entries)} segments found")
                for entry in entries:
                    speaker = entry.get("speaker_id", "speaker_0")
                    speaker_ids.add(speaker)
                    segments.append({
                        "speaker_id": speaker,
                        "start_seconds": entry.get("start_time_seconds", 0.0),
                        "end_seconds": entry.get("end_time_seconds", 0.0),
                        "text": entry.get("transcript", ""),
                        "language": language,
                        "words": [],
                    })
            elif full_transcript:
                # No diarization data — use full transcript as single segment
                segments.append({
                    "speaker_id": "speaker_0",
                    "start_seconds": 0.0,
                    "end_seconds": 0.0,
                    "text": full_transcript,
                    "language": language,
                    "words": [],
                })
                speaker_ids.add("speaker_0")

    # Clean up batch output
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)

    # Build participants
    participants = []
    for sid in sorted(speaker_ids):
        idx_str = sid.replace("speaker_", "").replace("SPEAKER_", "")
        try:
            idx = int(idx_str)
        except ValueError:
            idx = 0
        participants.append({
            "speaker_id": sid,
            "label": f"Speaker {idx}",
            "is_self": idx == 0 or idx == 1,
        })

    return _build_unified_transcript(
        transcript_id=transcript_id,
        audio_path=audio_path,
        source="meeting",
        segments=segments,
        full_transcript=full_transcript,
        language=language,
        participants=participants,
    )


def translate_text(text: str, source_lang: str = "ta-IN", target_lang: str = "en-IN") -> str:
    """Translate text between languages using Sarvam AI.

    Supports all 22 Indian languages + English.
    """
    client = get_client()
    result = client.text.translate(
        input=text,
        source_language_code=source_lang,
        target_language_code=target_lang,
        mode="modern-colloquial",
    )
    return result.translated_text


def _transcribe_chunked(audio_path: str, source: str) -> dict:
    """Split long audio into chunks, transcribe each, merge results."""
    chunk_dir = os.path.join(os.path.dirname(audio_path), "chunks")
    os.makedirs(chunk_dir, exist_ok=True)

    print(f"[Sarvam] Audio is {_get_audio_duration(audio_path):.1f}s — splitting into chunks")
    chunks = _split_audio(audio_path, chunk_dir)
    print(f"[Sarvam] Split into {len(chunks)} chunks")

    client = get_client()
    chunk_results = []

    for i, chunk_info in enumerate(chunks):
        print(f"[Sarvam] Transcribing chunk {i+1}/{len(chunks)} ({chunk_info['start_seconds']:.1f}s - {chunk_info['end_seconds']:.1f}s)")
        result = _transcribe_single(client, chunk_info["path"])
        chunk_results.append((chunk_info, result))

    transcript = _merge_chunk_results(chunk_results, audio_path)
    transcript["source"] = source

    # Clean up chunk files
    for chunk_info in chunks:
        try:
            os.remove(chunk_info["path"])
        except OSError:
            pass
    try:
        os.rmdir(chunk_dir)
    except OSError:
        pass

    return transcript


def _parse_rest_response(result, audio_path: str) -> dict:
    """Parse Sarvam REST API response into unified transcript format."""
    transcript_id = str(uuid.uuid4())

    segments = []
    if hasattr(result, "transcript") and result.transcript:
        segment = {
            "speaker_id": "speaker_0",
            "start_seconds": 0.0,
            "end_seconds": 0.0,
            "text": result.transcript,
            "language": getattr(result, "language_code", "unknown"),
            "words": [],
        }

        if hasattr(result, "timestamps") and result.timestamps:
            ts = result.timestamps
            words = getattr(ts, "words", []) or []
            starts = getattr(ts, "start_time_seconds", []) or []
            ends = getattr(ts, "end_time_seconds", []) or []

            for i, word in enumerate(words):
                segment["words"].append({
                    "word": word,
                    "start": starts[i] if i < len(starts) else 0.0,
                    "end": ends[i] if i < len(ends) else 0.0,
                })

            if ends:
                segment["end_seconds"] = ends[-1]

        segments.append(segment)

    return _build_unified_transcript(
        transcript_id=transcript_id,
        audio_path=audio_path,
        source="voice_note",
        segments=segments,
        full_transcript=getattr(result, "transcript", ""),
        language=getattr(result, "language_code", "unknown"),
    )


def _parse_diarized_response(result, audio_path: str) -> dict:
    """Parse Sarvam diarized response into unified transcript format."""
    transcript_id = str(uuid.uuid4())

    segments = []
    speaker_ids = set()

    if hasattr(result, "diarized_transcript") and result.diarized_transcript:
        entries = getattr(result.diarized_transcript, "entries", []) or []
        for entry in entries:
            speaker = getattr(entry, "speaker_id", "speaker_0")
            speaker_ids.add(speaker)
            segments.append({
                "speaker_id": speaker,
                "start_seconds": getattr(entry, "start_time_seconds", 0.0),
                "end_seconds": getattr(entry, "end_time_seconds", 0.0),
                "text": getattr(entry, "transcript", ""),
                "language": getattr(result, "language_code", "unknown"),
                "words": [],
            })
    elif hasattr(result, "transcript") and result.transcript:
        segments.append({
            "speaker_id": "speaker_0",
            "start_seconds": 0.0,
            "end_seconds": 0.0,
            "text": result.transcript,
            "language": getattr(result, "language_code", "unknown"),
            "words": [],
        })
        speaker_ids.add("speaker_0")

    participants = []
    for sid in sorted(speaker_ids):
        idx = int(sid.replace("speaker_", "")) if "speaker_" in sid else 0
        participants.append({
            "speaker_id": sid,
            "label": f"Speaker {idx}",
            "is_self": idx == 0,
        })

    return _build_unified_transcript(
        transcript_id=transcript_id,
        audio_path=audio_path,
        source="meeting",
        segments=segments,
        full_transcript=getattr(result, "transcript", ""),
        language=getattr(result, "language_code", "unknown"),
        participants=participants,
    )


def _build_unified_transcript(
    transcript_id: str,
    audio_path: str,
    source: str,
    segments: list,
    full_transcript: str,
    language: str,
    participants: Optional[list] = None,
) -> dict:
    """Build the unified transcript JSON format."""
    if participants is None:
        participants = [{"speaker_id": "speaker_0", "label": "Speaker 0", "is_self": True}]

    detected_languages = set()
    for seg in segments:
        if seg.get("language"):
            detected_languages.add(seg["language"])

    duration = max((s["end_seconds"] for s in segments), default=0.0)

    return {
        "id": transcript_id,
        "recording_id": Path(audio_path).stem,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "language": {
            "primary": language,
            "detected": list(detected_languages) if detected_languages else [language],
            "is_code_mixed": len(detected_languages) > 1,
        },
        "participants": participants,
        "segments": segments,
        "full_transcript": full_transcript or "\n".join(s["text"] for s in segments),
        "processing": {
            "engine": "sarvam",
            "model": "saaras:v3",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "audio_preprocessing": ["pyloudnorm"],
        },
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python sarvam_client.py <audio.wav> [meeting|voice_note] [num_speakers]")
        sys.exit(1)

    audio_file = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "voice_note"
    num_speakers = int(sys.argv[3]) if len(sys.argv) > 3 else None

    if mode == "meeting":
        result = transcribe_meeting(audio_file, num_speakers)
    else:
        result = transcribe_short(audio_file)

    print(json.dumps(result, indent=2, ensure_ascii=False))
