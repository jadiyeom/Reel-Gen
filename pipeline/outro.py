"""Build the optional image outro once, then stitch it to every video.

Uses the Backspace artwork by default rather than generating a second branding card.
The whole outro remains opt-in — enable it with OUTRO=true.
"""
from __future__ import annotations

from . import config
from .util import ffprobe_duration, log, run, step

W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS
DUR = config.OUTRO_SECONDS


def build_outro_vo() -> None:
    """Generate the outro call-to-action voiceover once (cached)."""
    if config.OUTRO_VO.exists():
        return
    if not config.OPENAI_API_KEY:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", "1.6", "-q:a", "9", str(config.OUTRO_VO)])
        return
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    with client.audio.speech.with_streaming_response.create(
        model=config.TTS_MODEL, voice=config.TTS_VOICE,
        input=config.OUTRO_VO_TEXT,
        instructions="Warm, clear, confident call to action. Friendly, not pushy.",
        response_format="mp3",
    ) as response:
        response.stream_to_file(str(config.OUTRO_VO))
    log("outro voiceover generated")


def build_outro(force: bool = False):
    out = config.PREBUILT_OUTRO
    if out.exists() and not force:
        return out
    step("Build outro (once)")

    image = config.DEFAULT_OUTRO_IMAGE
    if not image.is_file():
        raise FileNotFoundError(f"Default Backspace outro image not found: {image}")

    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xF4E9D2,"
          f"fps={FPS},fade=t=in:st=0:d=0.4,fade=t=out:st={DUR-0.4:.2f}:d=0.4,"
          f"setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{DUR}", "-i", str(image),
         "-vf", vf, "-r", str(FPS), "-t", f"{DUR}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])
    log(f"outro -> {out.name} ({ffprobe_duration(out):.2f}s)")
    return out
