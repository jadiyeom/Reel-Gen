"""Build the optional branded outro once, then stitch it to every video.

A true-portrait end card (logo + brand name + tagline + CTA), rendered crisply via
HTML. Shown STATIC (no zoom, so it never shakes) with a clean fade. A short
call-to-action voiceover (config.OUTRO_VO_TEXT) is mixed in during assemble. The
whole outro is opt-in — enable it with OUTRO=true and set your BRAND_* values.
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

    from .cards import render_outro_card
    if not config.OUTRO_CARD_PNG.exists() or force:
        render_outro_card()

    vf = (f"fps={FPS},fade=t=in:st=0:d=0.4,fade=t=out:st={DUR-0.4:.2f}:d=0.4,"
          f"setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{DUR}", "-i", str(config.OUTRO_CARD_PNG),
         "-vf", vf, "-r", str(FPS), "-t", f"{DUR}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])
    log(f"outro -> {out.name} ({ffprobe_duration(out):.2f}s)")
    return out
