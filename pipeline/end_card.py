"""Append a branded, silent 'Follow for more' end card to a finished video."""
from __future__ import annotations

import os
from pathlib import Path

from . import config
from .cards import render_outro_card
from .util import ffprobe_duration, log, run


def append_follow_card_to_video(video_path: Path, logo_path: Path | None = None) -> Path:
    """Render a per-video end card and append it without changing the source audio.

    The card and intermediate clip live beside this video's work files, rather
    than using the globally cached OUTRO asset. That keeps different uploaded
    logos from bleeding between simultaneous renders.
    """
    video_path = Path(video_path).resolve()
    work_dir = video_path.parent / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    card_path = work_dir / "follow_for_more_card.png"
    outro_path = work_dir / "follow_for_more_clip.mp4"
    combined_path = work_dir / "final_with_follow.mp4"
    duration = max(2.0, float(config.OUTRO_SECONDS))
    fade = min(0.3, duration / 4)
    brand_name = str(config.BRAND.get("name") or "").strip()
    if not brand_name or brand_name.lower() == "your brand":
        brand_name = "ReelGen"

    render_outro_card(
        out=card_path,
        logo_path=logo_path,
        cta="Follow for more",
        name=brand_name,
    )

    vf = (
        f"fps={config.FPS},format=yuv420p,setsar=1,"
        f"fade=t=in:st=0:d={fade:.3f},"
        f"fade=t=out:st={duration-fade:.3f}:d={fade:.3f}"
    )
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(config.FPS), "-t", f"{duration:.3f}",
        "-i", str(card_path),
        "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", vf, "-r", str(config.FPS), "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(outro_path),
    ])

    # Normalize stream formats before concatenating so MP4 timestamp/timebase
    # differences do not create a broken tail on Windows or Linux.
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
        raise RuntimeError("FFmpeg did not produce the video with the Follow for more end card.")
    os.replace(combined_path, video_path)
    log(f"follow end card appended ({duration:.2f}s; final={ffprobe_duration(video_path):.2f}s)")
    return video_path
