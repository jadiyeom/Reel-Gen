"""Append the selected Backspace outro image to a rendered video."""
from __future__ import annotations

import os
from pathlib import Path

from . import config
from .util import ffprobe_duration, log, run


def resolve_outro_image(outro_image_path: Path | None = None) -> Path:
    """Use a per-render custom image when supplied, otherwise the default artwork."""
    image = Path(outro_image_path).resolve() if outro_image_path else config.DEFAULT_OUTRO_IMAGE
    if not image.is_file():
        raise FileNotFoundError(
            f"Outro image not found: {image}. Restore assets/brand/backspace_outro.webp "
            "or upload a custom outro image."
        )
    return image


def append_outro_image_to_video(video_path: Path, outro_image_path: Path | None = None) -> Path:
    """Append one still-image outro; do not generate an additional branding card."""
    video_path = Path(video_path).resolve()
    outro_image = resolve_outro_image(outro_image_path)
    work_dir = video_path.parent / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    outro_path = work_dir / "selected_outro_clip.mp4"
    combined_path = work_dir / "final_with_outro.mp4"
    duration = max(2.0, float(config.OUTRO_SECONDS))
    fade = min(0.3, duration / 4)

    # Fit the complete artwork inside either supported canvas. The 16:9 format
    # gets a parchment background rather than cropping the portrait design.
    vf = (
        f"scale={config.WIDTH}:{config.HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={config.WIDTH}:{config.HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0xF4E9D2,"
        f"fps={config.FPS},format=yuv420p,setsar=1,"
        f"fade=t=in:st=0:d={fade:.3f},"
        f"fade=t=out:st={duration-fade:.3f}:d={fade:.3f}"
    )
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(config.FPS), "-t", f"{duration:.3f}",
        "-i", str(outro_image),
        "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", vf, "-r", str(config.FPS), "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(outro_path),
    ])

    # Normalize streams before concatenating to handle MP4 timebase differences.
    filter_complex = (
        f"[0:v]fps={config.FPS},setpts=PTS-STARTPTS,format=yuv420p[v0];"
        "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "asetpts=PTS-STARTPTS[a0];"
        f"[1:v]fps={config.FPS},setpts=PTS-STARTPTS,format=yuv420p[v1];"
        "[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]"
    )
    run([
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(outro_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", str(combined_path),
    ])
    if not combined_path.is_file() or combined_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not produce the video with its outro image.")
    os.replace(combined_path, video_path)
    log(f"outro image appended ({outro_image.name}; {duration:.2f}s; final={ffprobe_duration(video_path):.2f}s)")
    return video_path
