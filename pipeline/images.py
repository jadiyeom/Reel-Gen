"""Stage: cinematic still generation for every scene.

Two backends, switched by IMAGE_BACKEND:
  - "fal":   Flux dev via fal.ai (best quality, ~$0.025/image).
  - "local": SDXL-Turbo on the GPU (free). Few-step, fits the 6 GB 3060.

Output is always a 1080x1920 cover-cropped PNG, which is then animated by animate.py.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .models import Scene
from .util import log

_pipe = None  # cached local pipeline


def _cover_crop(src: Path, dst: Path) -> None:
    from PIL import Image

    img = Image.open(src).convert("RGB")
    tw, th = config.WIDTH, config.HEIGHT
    scale = max(tw / img.width, th / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    img.crop((left, top, left + tw, top + th)).save(dst)


def _local_pipe():
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import AutoPipelineForText2Image

    log(f"loading {config.SDXL_MODEL} (first run downloads weights) ...")
    _pipe = AutoPipelineForText2Image.from_pretrained(
        config.SDXL_MODEL, torch_dtype=torch.float16, variant="fp16"
    )
    _pipe.enable_model_cpu_offload()
    _pipe.set_progress_bar_config(disable=True)
    return _pipe


def _gen_local(prompt: str, raw: Path) -> None:
    pipe = _local_pipe()
    if config.ASPECT_RATIO == "16:9":
        width, height = 1024, 576
    else:
        width, height = 576, 1024
    image = pipe(prompt=prompt, num_inference_steps=4, guidance_scale=0.0,
                 height=height, width=width).images[0]
    image.save(raw)


def _gen_fal(prompt: str, raw: Path) -> str:
    import fal_client
    import requests

    result = fal_client.subscribe(
        config.FAL_FLUX_MODEL,
        arguments={"prompt": prompt, "image_size": config.IMAGE_SIZE,
                   "num_images": 1, "num_inference_steps": config.IMAGE_STEPS,
                   "enable_safety_checker": True},
    )
    url = result["images"][0]["url"]
    raw.write_bytes(requests.get(url, timeout=120).content)
    return url


def generate_image(image_prompt: str, out: Path, style: str | None = None) -> str:
    """Generate a cinematic still from a content prompt; returns the fal url (if any)."""
    prompt = f"{image_prompt}. {style if style is not None else config.IMAGE_STYLE}"
    raw = out.with_name(out.stem + "_raw.png")
    url = _gen_fal(prompt, raw) if config.IMAGE_BACKEND == "fal" else (_gen_local(prompt, raw) or "")
    _cover_crop(raw, out)
    if raw.exists():
        raw.unlink()
    return url


def render_scene(scene: Scene, out: Path) -> dict:
    """Generate the scene still. Returns {'path', 'url'}."""
    url = generate_image(scene.image_prompt, out)
    return {"path": out, "url": url}
