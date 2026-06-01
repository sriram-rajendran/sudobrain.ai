"""Audio preprocessing: denoise and normalize for optimal transcription."""

import os
import numpy as np
import soundfile as sf
import pyloudnorm as pyln


def normalize_loudness(audio: np.ndarray, sample_rate: int, target_lufs: float = -16.0) -> np.ndarray:
    """Normalize audio to target LUFS loudness level.

    This is critical for soft speech — brings quiet audio to a standard level
    without clipping loud parts.
    """
    meter = pyln.Meter(sample_rate)
    current_loudness = meter.integrated_loudness(audio)

    # If audio is completely silent, skip normalization
    if current_loudness == float("-inf"):
        return audio

    normalized = pyln.normalize.loudness(audio, current_loudness, target_lufs)
    return normalized


def convert_for_sarvam(input_path: str, output_path: str, target_sr: int = 16000) -> str:
    """Convert audio to Sarvam-optimal format: 16kHz mono WAV.

    Sarvam works best with 16kHz PCM. We convert from whatever format
    the capture layer produces (typically 48kHz stereo 32-bit float).
    """
    audio, sr = sf.read(input_path)

    # Convert stereo to mono if needed
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # Resample if needed (simple decimation for 48k->16k, proper resampling otherwise)
    if sr != target_sr:
        # Use scipy for proper resampling
        from scipy.signal import resample
        num_samples = int(len(audio) * target_sr / sr)
        audio = resample(audio, num_samples)
        sr = target_sr

    # Normalize loudness
    audio = normalize_loudness(audio, sr)

    # Write as 16-bit PCM WAV (Sarvam optimal format)
    sf.write(output_path, audio, sr, subtype="PCM_16")
    return output_path


def process_audio(input_path: str, output_dir: str) -> str:
    """Full audio preprocessing pipeline.

    Takes raw audio from capture layer, applies:
    1. Loudness normalization (fixes soft speech)
    2. Format conversion (16kHz mono WAV)

    Note: DeepFilterNet denoising is optional and added in Phase 2
    when the pip package is installed. For POC, normalization alone
    gives significant improvement for soft speech.

    Returns path to the processed audio file.
    """
    os.makedirs(output_dir, exist_ok=True)

    basename = os.path.splitext(os.path.basename(input_path))[0]
    processed_path = os.path.join(output_dir, f"{basename}_processed.wav")

    # Try DeepFilterNet if available, otherwise skip denoising
    denoised_path = input_path
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio

        model, df_state, _ = init_df()
        audio, _ = load_audio(input_path, sr=df_state.sr())
        enhanced = enhance(model, df_state, audio)
        denoised_path = os.path.join(output_dir, f"{basename}_denoised.wav")
        save_audio(denoised_path, enhanced, df_state.sr())
        print(f"[DeepFilterNet] Denoised: {denoised_path}")
    except ImportError:
        print("[DeepFilterNet] Not installed, skipping denoising. Install with: pip install deepfilternet")

    # Normalize + convert format
    convert_for_sarvam(denoised_path, processed_path)
    print(f"[Processing] Normalized and converted: {processed_path}")

    return processed_path


def mix_meeting_audio(mic_path: str, system_path: str, output_path: str) -> str:
    """Mix microphone and system audio into a single file for transcription.

    Both tracks are normalized and mixed at equal volume.
    If system audio file doesn't exist or is empty, returns mic audio only.
    """
    if not os.path.exists(system_path):
        print("[Processing] No system audio file found, using mic only")
        return mic_path

    try:
        mic_audio, mic_sr = sf.read(mic_path)
        sys_audio, sys_sr = sf.read(system_path)
    except Exception as e:
        print(f"[Processing] Error reading audio files: {e}, using mic only")
        return mic_path

    # Check if system audio has actual content (not just silence)
    if len(sys_audio) == 0 or np.max(np.abs(sys_audio)) < 0.001:
        print("[Processing] System audio is silent, using mic only")
        return mic_path

    # Convert both to mono
    if len(mic_audio.shape) > 1:
        mic_audio = np.mean(mic_audio, axis=1)
    if len(sys_audio.shape) > 1:
        sys_audio = np.mean(sys_audio, axis=1)

    # Resample to match (use mic sample rate as reference)
    if sys_sr != mic_sr:
        from scipy.signal import resample
        num_samples = int(len(sys_audio) * mic_sr / sys_sr)
        sys_audio = resample(sys_audio, num_samples)

    # Pad shorter track to match longer
    max_len = max(len(mic_audio), len(sys_audio))
    if len(mic_audio) < max_len:
        mic_audio = np.pad(mic_audio, (0, max_len - len(mic_audio)))
    if len(sys_audio) < max_len:
        sys_audio = np.pad(sys_audio, (0, max_len - len(sys_audio)))

    # Mix at equal volume (0.5 each to prevent clipping)
    mixed = 0.5 * mic_audio + 0.5 * sys_audio

    sf.write(output_path, mixed.astype(np.float32), mic_sr, subtype="FLOAT")
    print(f"[Processing] Mixed mic + system audio: {output_path} ({max_len / mic_sr:.1f}s)")
    return output_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python audio_processor.py <input.wav> [output_dir]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(input_file)
    result = process_audio(input_file, output_dir)
    print(f"Processed audio saved to: {result}")
