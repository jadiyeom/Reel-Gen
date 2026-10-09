"""Isolated adapter for the installed official Kokoro KPipeline package."""
from __future__ import annotations

import wave
from functools import lru_cache
from pathlib import Path


# Voice packs published by hexgrad/Kokoro-82M (verified against the model repo).
VOICE_IDS = frozenset("""
af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky
am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa
bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis
ef_dora em_alex em_santa ff_siwis hf_alpha hf_beta hm_omega hm_psi
if_sara im_nicola jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo
pf_dora pm_alex pm_santa zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi
zm_yunjian zm_yunxi zm_yunxia zm_yunyang
""".split())

# KPipeline currently returns waveform tensors without a sample-rate field.
# The installed official package's own WAV writer and its model vocoder use 24 kHz.
SAMPLE_RATE = 24_000


def _lang_code(language: str) -> str:
    try:
        from kokoro.pipeline import ALIASES, LANG_CODES
    except ImportError as exc:
        raise RuntimeError("Kokoro is missing from this project's .venv; install the official kokoro package into the existing environment.") from exc
    normalized = language.strip().lower()
    code = ALIASES.get(normalized, normalized)
    if code not in LANG_CODES:
        raise ValueError(f"Unsupported Kokoro language '{language}'. Available: {', '.join(sorted(LANG_CODES))}")
    return code


def _voice_error(voice: str, lang: str) -> ValueError:
    choices = sorted(v for v in VOICE_IDS if v.startswith(lang))
    cached = _cached_voice_ids()
    detail = f"Cached voice packs: {', '.join(cached) if cached else 'none'}"
    return ValueError(f"KOKORO_VOICE '{voice}' is not a known voice for language '{lang}'. "
                      f"Available voice IDs for this language: {', '.join(choices) or 'none'}. {detail}.")


def _cached_voice_ids() -> list[str]:
    try:
        # Inspect the standard Hub cache without assuming a user-specific path.
        import os
        root = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
        voices = []
        for candidate in root.glob("models--hexgrad--Kokoro-82M/snapshots/*/voices/*.pt"):
            voices.append(candidate.stem)
        return sorted(set(voices))
    except Exception:  # noqa: BLE001
        return []


@lru_cache(maxsize=4)
def _pipeline(lang: str, repo_id: str):
    from kokoro import KPipeline
    try:
        return KPipeline(lang_code=lang, repo_id=repo_id)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not initialize Kokoro KPipeline for '{lang}' ({repo_id}): {exc}") from exc


def generate_speech(text: str, output_path: Path, voice: str, speed: float,
                    language: str, repo_id: str) -> float:
    """Synthesize text to mono 24 kHz PCM WAV and return its measured duration."""
    from .util import ffprobe_duration

    text = text.strip()
    if not text:
        raise ValueError("Kokoro received empty narration text")
    if not 0.5 <= float(speed) <= 2.0:
        raise ValueError("KOKORO_SPEED must be between 0.5 and 2.0")
    lang = _lang_code(language)
    if voice not in VOICE_IDS or not voice.startswith(lang):
        raise _voice_error(voice, lang)

    try:
        import numpy as np
        pipeline = _pipeline(lang, repo_id)
        chunks = []
        for result in pipeline(text, voice=voice, speed=float(speed)):
            audio = getattr(result, "audio", None)
            if audio is None and getattr(result, "output", None) is not None:
                audio = getattr(result.output, "audio", None)
            if audio is not None:
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not chunks:
            raise RuntimeError("Kokoro returned no audio samples")
        samples = np.concatenate(chunks)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ValueError, RuntimeError)) and "Kokoro" in str(exc):
            raise
        raise RuntimeError(f"Kokoro speech generation failed for voice '{voice}': {exc}") from exc
    duration = ffprobe_duration(output_path)
    if duration <= 0:
        raise RuntimeError(f"Kokoro wrote an unreadable WAV file: {output_path}")
    return duration
