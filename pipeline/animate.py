"""Animate a still into a living clip via an image-to-video model.

Default model is Wan 2.2 5B on fal.ai (~$0.15/clip) — the quality/cost sweet spot.
Reuses the fal image URL when available so we don't re-upload.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .models import Scene
from .util import log


def i2v(image_path: Path, image_url: str, motion_prompt: str, out: Path) -> Path:
    """Animate an image with the configured i2v model; download mp4 to `out`."""
    import fal_client
    import requests

    url = image_url or fal_client.upload_file(str(image_path))
    prompt = motion_prompt or "subtle cinematic camera motion, gentle ambient movement"
    log(f"animating via {config.I2V_MODEL.split('/')[-2]} -> {out.name}")
    result = fal_client.subscribe(config.I2V_MODEL, arguments={"image_url": url, "prompt": prompt})
    video = result.get("video")
    video_url = video["url"] if isinstance(video, dict) else video
    out.write_bytes(requests.get(video_url, timeout=300).content)
    return out


def i2v_clip(image_path: Path, image_url: str, scene: Scene, out: Path) -> Path:
    """Animate a script scene's still (runtime generate-on-miss path)."""
    return i2v(image_path, image_url, scene.motion_prompt, out)
