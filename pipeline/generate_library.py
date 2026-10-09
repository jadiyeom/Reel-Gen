"""Generate the clip library from inventory.csv.

For each row: Flux image -> Wan animation -> normalized 1080x1920 clip, saved by its
id (title), embedded, and recorded in the catalog. Skips rows already generated, so
it's resumable and never double-charges. Supports a limit for cheap validation.
"""
from __future__ import annotations

import csv

from . import animate, config, images, library
from .util import ffprobe_duration, log, run, step

PER_CLIP_COST = 0.175   # ~$0.025 image + ~$0.15 Wan 2.2 5B


def _read_inventory() -> list[dict]:
    with open(config.INVENTORY_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _normalize(src, dst) -> None:
    """Cover-fit the i2v clip to 1080x1920, keep its native length."""
    vf = (f"scale={config.WIDTH}:{config.HEIGHT}:force_original_aspect_ratio=increase,"
          f"crop={config.WIDTH}:{config.HEIGHT},fps={config.FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-i", str(src), "-an", "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(dst)])


def generate(limit: int | None = None, only_missing: bool = True) -> None:
    rows = _read_inventory()
    todo = [r for r in rows if not (only_missing and library.has(r["id"]))]
    if limit:
        todo = todo[:limit]
    step(f"Generate library — {len(todo)} clip(s) to make "
         f"(est. ${len(todo) * PER_CLIP_COST:.2f}); {library.count()} already in catalog")
    if not config.FAL_KEY:
        log("no FAL_KEY — cannot generate. Aborting.")
        return

    for i, row in enumerate(todo, 1):
        cid = row["id"]
        log(f"[{i}/{len(todo)}] {cid}")
        img = config.LIB_IMAGES / f"{cid}.png"
        clip = config.LIB_CLIPS / f"{cid}.mp4"
        raw = config.LIB_CLIPS / f"{cid}_raw.mp4"
        try:
            url = images.generate_image(row["image_prompt"], img)
            animate.i2v(img, url, row["motion_prompt"], raw)
            _normalize(raw, clip)
            if raw.exists():
                raw.unlink()
            dur = ffprobe_duration(clip)
            emb = library.embed(f"{row['description']} ({row['group']}, {row['lighting']})")
            library.add_clip(row, img, clip, dur, emb)
            log(f"    saved {clip.name} ({dur:.1f}s) · catalog now {library.count()}")
        except Exception as e:  # noqa: BLE001 - keep going, resume later
            log(f"    FAILED {cid}: {e}")

    s = library.stats()
    print(f"\n[LIBRARY] {s['total']} clips total: {s['by_group']}")
