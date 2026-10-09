"""Per-scene speech synthesis. Kokoro WAV is the local default; OpenAI is opt-in."""
from __future__ import annotations

from pathlib import Path
import hashlib

from . import config
from .models import Script
from .util import ffprobe_duration, log, run, step


def _apply_tempo(src: Path, dst: Path) -> None:
    if abs(config.SPEECH_TEMPO - 1.0) < 0.01:
        if src != dst:
            src.replace(dst)
        return
    run(["ffmpeg", "-y", "-i", str(src), "-filter:a",
         f"atempo={config.SPEECH_TEMPO:.3f}", str(dst)])
    if src != dst and src.exists():
        src.unlink()


def _silent_clip(text: str, out: Path) -> float:
    words = max(1, len(text.split()))
    dur = max(config.MIN_SCENE_SECONDS,
              min(config.MAX_SCENE_SECONDS,
                  words / config.WORDS_PER_MINUTE * 60 / config.SPEECH_TEMPO + 0.4))
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.3f}", "-q:a", "9", str(out)])
    return dur


def _silent_wav(out: Path, duration: float = 0.75) -> float:
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(out)])
    return ffprobe_duration(out)


def _tts_clip(client, text: str, out: Path) -> float:
    raw = out.with_name(out.stem + "_raw.mp3")
    with client.audio.speech.with_streaming_response.create(
        model=config.TTS_MODEL, voice=config.TTS_VOICE, input=text,
        instructions=config.TTS_INSTRUCTIONS, response_format="mp3",
    ) as response:
        response.stream_to_file(str(raw))
    _apply_tempo(raw, out)
    return ffprobe_duration(out)


def synthesize(audio_dir: Path, script: Script) -> list[dict]:
    step("Voiceover")
    backend = config.TTS_BACKEND
    client = None
    if backend == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("TTS_BACKEND=openai requires OPENAI_API_KEY. Use TTS_BACKEND=kokoro for local speech.")
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)
    elif backend not in ("kokoro", "silent"):
        raise ValueError(f"Unsupported TTS_BACKEND '{backend}'. Choose kokoro or explicitly openai.")
    if backend == "kokoro":
        from . import kokoro_tts
        log(f"local Kokoro voice={config.KOKORO_VOICE} speed={config.KOKORO_SPEED:g} lang={config.KOKORO_LANG}")

    out_info: list[dict] = []
    for scene in script.scenes:
        audio_dir.mkdir(parents=True, exist_ok=True)
        ext = ".wav" if backend == "kokoro" else ".mp3"
        out = audio_dir / f"scene_{scene.index:02d}{ext}"
        text = scene.narration.strip()
        fingerprint = hashlib.sha256(("|".join((text, backend, config.TTS_MODEL, config.TTS_VOICE,
                                                   config.TTS_INSTRUCTIONS, str(config.SPEECH_TEMPO),
                                                   config.KOKORO_VOICE, str(config.KOKORO_SPEED),
                                                   config.KOKORO_LANG, config.KOKORO_REPO_ID))).encode()).hexdigest()
        marker = out.with_suffix(".sha256")
        if not out.exists() or not marker.exists() or marker.read_text(encoding="utf-8") != fingerprint:
            if not text:
                dur = _silent_wav(out) if backend == "kokoro" else _silent_clip(text, out)
            elif backend == "kokoro":
                dur = kokoro_tts.generate_speech(text, out, config.KOKORO_VOICE,
                                                 config.KOKORO_SPEED, config.KOKORO_LANG,
                                                 config.KOKORO_REPO_ID)
            elif backend == "openai":
                dur = _tts_clip(client, text, out)
            else:
                dur = _silent_clip(text, out)
            marker.write_text(fingerprint, encoding="utf-8")
        else:
            dur = ffprobe_duration(out)
        dur = max(0.05, dur + (config.SCENE_PAD if text else 0.0))
        log(f"scene {scene.index}: {dur:.2f}s")
        out_info.append({"index": scene.index, "path": str(out), "duration": round(dur, 3)})
    return out_info
