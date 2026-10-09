"""Populate the clip library from FREE real stock footage (Pexels / Pixabay).

Real footage = no AI mush, license-free, and $0. Each clip is downloaded, cropped
to 1080x1920, trimmed, tagged, embedded, and added to the same catalog the matcher
uses. AI generation (Flux+Wan) remains the fallback for shots stock can't cover.
"""
from __future__ import annotations

import csv
from pathlib import Path

import requests

from . import config, library
from .util import ffprobe_duration, log, run, step

PEXELS_SEARCH = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH = "https://pixabay.com/api/videos/"


def _best_file(video: dict) -> str | None:
    """Best portrait (or largest) file link from a single Pexels video."""
    best, best_score = None, -1.0
    for f in video.get("video_files", []):
        w, h = f.get("width") or 0, f.get("height") or 0
        if not w or not h:
            continue
        portrait = h >= w
        score = (2.0 if portrait else 0.0) + min(h, 1920) / 1920 - abs(h - 1920) / 4000
        if score > best_score:
            best, best_score = f.get("link"), score
    return best


def _search_pexels(query: str, n: int) -> list[str]:
    """Return up to n distinct video file links for a query."""
    r = requests.get(PEXELS_SEARCH, headers={"Authorization": config.PEXELS_API_KEY},
                     params={"query": query, "orientation": "portrait",
                             "per_page": max(15, n * 3), "size": "medium"}, timeout=60)
    r.raise_for_status()
    links = []
    for v in r.json().get("videos", []):
        link = _best_file(v)
        if link:
            links.append(link)
        if len(links) >= n:
            break
    return links


def _search_pixabay(query: str) -> str | None:
    r = requests.get(PIXABAY_SEARCH, params={"key": config.PIXABAY_API_KEY, "q": query,
                     "video_type": "film", "per_page": 12}, timeout=60)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    for h in hits:
        vids = h.get("videos", {})
        for q in ("large", "medium", "small"):
            if vids.get(q, {}).get("url"):
                return vids[q]["url"]
    return None


def _normalize(src: Path, dst: Path) -> None:
    """Center-crop to 1080x1920, trim a clean segment, drop audio."""
    start = 0.5 if ffprobe_duration(src) > config.LIB_CLIP_SECONDS + 1 else 0.0
    vf = (f"scale={config.WIDTH}:{config.HEIGHT}:force_original_aspect_ratio=increase,"
          f"crop={config.WIDTH}:{config.HEIGHT},fps={config.FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-ss", f"{start}", "-i", str(src), "-an",
         "-t", f"{config.LIB_CLIP_SECONDS}", "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(dst)])


def _store(cid: str, row: dict, link: str) -> None:
    raw = config.LIB_CLIPS / f"{cid}_raw.mp4"
    clip = config.LIB_CLIPS / f"{cid}.mp4"
    raw.write_bytes(requests.get(link, timeout=180).content)
    _normalize(raw, clip)
    raw.unlink(missing_ok=True)
    libimg = config.LIB_IMAGES / f"{cid}.jpg"   # poster frame for the dashboard
    run(["ffmpeg", "-y", "-ss", "1", "-i", str(clip), "-frames:v", "1", str(libimg)])
    cat = {"id": cid, "group": row["group"], "lighting": row.get("lighting", ""),
           "style": "stock", "description": row["description"],
           "image_prompt": row["description"], "motion_prompt": ""}
    library.add_clip(cat, libimg, clip, ffprobe_duration(clip),
                     library.embed(f"{row['description']} ({row['group']})"))


def fetch_variants(row: dict, n: int) -> int:
    """Fetch up to n distinct variants for a query (ids: {base}_v1.._vN)."""
    links = _search_pexels(row["query"], n) if config.PEXELS_API_KEY else []
    if not links and config.PIXABAY_API_KEY:
        one = _search_pixabay(row["query"])
        links = [one] if one else []
    saved = 0
    for idx, link in enumerate(links, 1):
        cid = f"{row['id']}_v{idx}"
        if library.has(cid):
            saved += 1
            continue
        try:
            _store(cid, row, link)
            saved += 1
            log(f"    {cid} saved · catalog now {library.count()}")
        except Exception as e:  # noqa: BLE001
            log(f"    FAILED {cid}: {e}")
    return saved


def fetch_library(inventory_csv: Path = None, limit: int | None = None,
                  variants: int = None, only_missing: bool = True) -> None:
    inv = inventory_csv or (config.LIBRARY / "stock_inventory.csv")
    n = variants or config.STOCK_VARIANTS
    with open(inv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
    step(f"Fetch stock library — {len(rows)} queries x {n} variants from Pexels (FREE); "
         f"{library.count()} already in catalog")
    if not (config.PEXELS_API_KEY or config.PIXABAY_API_KEY):
        log("no PEXELS_API_KEY / PIXABAY_API_KEY set — add one to .env (free).")
        return
    total = 0
    for i, row in enumerate(rows, 1):
        log(f"[{i}/{len(rows)}] {row['id']}  <-  '{row['query']}'")
        try:
            total += fetch_variants(row, n)
        except Exception as e:  # noqa: BLE001
            log(f"    FAILED query {row['id']}: {e}")
    print(f"\n[STOCK] library total {library.count()} clips")
