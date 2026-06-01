"""Local Whisper transcription — offline, free, fast on Apple Silicon.

Uses faster-whisper (CTranslate2) for efficient local transcription.
Supports 99 languages. Use Sarvam for Tamil-specific accuracy.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sudobrain.whisper")

_model = None
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")


def _get_model():
    """Load the Whisper model (lazy, cached)."""
    global _model
    if _model is not None:
        return _model

    try:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper model '%s' (first time may download)...", WHISPER_MODEL_SIZE)
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        logger.info("Whisper model loaded")
        return _model
    except Exception as e:
        logger.error("Failed to load Whisper: %s", e)
        return None


def is_available() -> bool:
    """Check if faster-whisper is installed."""
    try:
        from faster_whisper import WhisperModel
        return True
    except ImportError:
        return False


def transcribe(audio_path: str, language: str = None) -> dict:
    """Transcribe audio file using local Whisper model.

    Returns unified transcript format (same structure as sarvam_client).
    """
    model = _get_model()
    if not model:
        raise RuntimeError("Whisper model not available")

    logger.info("Transcribing with Whisper: %s", audio_path)

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segments = []
    full_text_parts = []

    for seg in segments_iter:
        segments.append({
            "speaker_id": "speaker_0",
            "start_seconds": seg.start,
            "end_seconds": seg.end,
            "text": seg.text.strip(),
            "language": info.language or "en",
            "words": [],
        })
        full_text_parts.append(seg.text.strip())

    duration = segments[-1]["end_seconds"] if segments else 0.0

    transcript = {
        "id": str(uuid.uuid4()),
        "recording_id": Path(audio_path).stem,
        "source": "whisper_local",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "language": {
            "primary": info.language or "en",
            "detected": [info.language] if info.language else ["en"],
            "is_code_mixed": False,
        },
        "participants": [{"speaker_id": "speaker_0", "label": "Speaker 0", "is_self": True}],
        "segments": segments,
        "full_transcript": " ".join(full_text_parts),
        "processing": {
            "engine": "whisper",
            "model": WHISPER_MODEL_SIZE,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "audio_preprocessing": ["faster-whisper"],
            "language_probability": round(info.language_probability, 2) if info.language_probability else 0,
        },
    }

    logger.info(
        "Whisper transcription complete: %.1fs, %d segments, language=%s (%.0f%%)",
        duration, len(segments), info.language, (info.language_probability or 0) * 100,
    )
    return transcript


def transcribe_with_diarization(audio_path: str, num_speakers: int = None) -> dict:
    """Transcribe with basic speaker change detection.

    Note: faster-whisper doesn't have native diarization.
    For proper speaker ID, use Sarvam's batch API instead.
    This provides segment-level timestamps without speaker labels.
    """
    return transcribe(audio_path)
