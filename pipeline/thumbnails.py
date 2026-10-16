"""Support for dual thumbnail variants (Thumbnail 1 & Thumbnail 2) per short.

Enables uploading, previewing, downloading, and selecting A/B thumbnail options
for social publishing (YouTube Shorts, Instagram Reels, TikTok, Facebook).
"""
from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any

from PIL import Image

from .util import read_json, write_json

ALLOWED_THUMBNAIL_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
MAX_THUMBNAIL_BYTES = 15 * 1024 * 1024  # 15 MB


def get_thumbnails_dir(video_dir: Path | str) -> Path:
    return Path(video_dir) / "thumbnails"


def _safe_unlink(path: Path) -> None:
    """Unlink a file safely, with Windows-specific retry if locked by another reader."""
    if not path.exists():
        return
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        import gc
        import time
        gc.collect()
        time.sleep(0.05)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def find_thumbnail_path(video_dir: Path | str, slot: int) -> Path | None:
    """Locate the thumbnail file for a slot (1 or 2), inspecting thumbnails/ then root."""
    if slot not in (1, 2):
        return None
    video_dir = Path(video_dir)
    thumb_dir = get_thumbnails_dir(video_dir)
    # Check thumbnails/ first
    if thumb_dir.exists():
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = thumb_dir / f"thumbnail_{slot}{ext}"
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
            candidate_short = thumb_dir / f"thumb_{slot}{ext}"
            if candidate_short.is_file() and candidate_short.stat().st_size > 0:
                return candidate_short

    # Check video_dir root as fallback
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = video_dir / f"thumbnail_{slot}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
        candidate_short = video_dir / f"thumb_{slot}{ext}"
        if candidate_short.is_file() and candidate_short.stat().st_size > 0:
            return candidate_short
    return None


def get_thumbnails(video_dir: Path) -> dict[str, Any]:
    """Return status and metadata for Thumbnail 1 and Thumbnail 2 of a video."""
    video_dir = Path(video_dir).resolve()
    manifest_path = video_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    manifest_thumbs = manifest.get("thumbnails", {}) if isinstance(manifest.get("thumbnails"), dict) else {}
    primary_slot = str(manifest_thumbs.get("primary") or "1")

    slots: dict[str, Any] = {}
    for slot in (1, 2):
        s_key = str(slot)
        path = find_thumbnail_path(video_dir, slot)
        info: dict[str, Any] = {
            "slot": slot,
            "exists": False,
            "filename": None,
            "url": None,
            "download_url": None,
            "width": 0,
            "height": 0,
            "size_bytes": 0,
            "is_primary": False,
        }
        if path and path.is_file():
            try:
                with Image.open(path) as img:
                    w, h = img.size
            except Exception:
                w, h = 0, 0
            size = path.stat().st_size
            info.update({
                "exists": True,
                "filename": path.name,
                "url": f"/media/{video_dir.name}/thumbnail/{slot}?t={int(path.stat().st_mtime)}",
                "download_url": f"/download/{video_dir.name}/thumbnail/{slot}",
                "width": w,
                "height": h,
                "size_bytes": size,
            })
        slots[s_key] = info

    # Determine primary slot (default to slot 1 if it exists, else 2 if it exists)
    if not slots.get(primary_slot, {}).get("exists"):
        if slots.get("1", {}).get("exists"):
            primary_slot = "1"
        elif slots.get("2", {}).get("exists"):
            primary_slot = "2"
        else:
            primary_slot = "1"

    if slots.get(primary_slot):
        slots[primary_slot]["is_primary"] = True

    primary_info = slots.get(primary_slot) or slots["1"]
    return {
        "1": slots["1"],
        "2": slots["2"],
        "slot_1": slots["1"],
        "slot_2": slots["2"],
        "primary": primary_slot,
        "primary_slot": int(primary_slot),
        "primary_info": primary_info,
        "count": sum(1 for s in (1, 2) if slots[str(s)]["exists"]),
    }


def save_thumbnail(
    video_dir: Path | str,
    slot: int,
    file_bytes: bytes,
    original_filename: str = "thumbnail.png",
    make_primary: bool | None = None,
) -> dict[str, Any]:
    """Validate and persist a thumbnail file for slot 1 or 2."""
    if slot not in (1, 2):
        raise ValueError(f"Thumbnail slot must be 1 or 2, got {slot}.")
    if not file_bytes:
        raise ValueError("Thumbnail file is empty.")
    if len(file_bytes) > MAX_THUMBNAIL_BYTES:
        raise ValueError(f"Thumbnail must be smaller than {MAX_THUMBNAIL_BYTES // (1024*1024)} MB.")

    video_dir = Path(video_dir)
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_THUMBNAIL_EXTS:
        raise ValueError(f"Thumbnail format {ext or '(none)'} is not supported. Use PNG, JPG, or WEBP.")

    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(file_bytes)) as img:
            width, height = img.size
            fmt = img.format or ext.lstrip(".").upper()
    except Exception as exc:
        raise ValueError("Uploaded file is not a valid, readable image.") from exc

    thumb_dir = get_thumbnails_dir(video_dir)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing files for this slot with different extensions
    for candidate_ext in ALLOWED_THUMBNAIL_EXTS:
        for prefix in ("thumbnail_", "thumb_"):
            _safe_unlink(thumb_dir / f"{prefix}{slot}{candidate_ext}")
            _safe_unlink(video_dir / f"{prefix}{slot}{candidate_ext}")

    target_path = thumb_dir / f"thumbnail_{slot}{ext}"
    target_path.write_bytes(file_bytes)

    # Update manifest
    manifest_path = video_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    manifest_thumbs = manifest.setdefault("thumbnails", {})
    manifest_thumbs[str(slot)] = {
        "filename": target_path.name,
        "width": width,
        "height": height,
        "format": fmt,
        "size_bytes": len(file_bytes),
    }

    # Decide primary
    if make_primary is True or (make_primary is None and "primary" not in manifest_thumbs):
        manifest_thumbs["primary"] = str(slot)

    write_json(manifest_path, manifest)
    return get_thumbnails(video_dir)


def delete_thumbnail(video_dir: Path | str, slot: int) -> dict[str, Any]:
    """Delete the thumbnail for a slot and update the manifest."""
    if slot not in (1, 2):
        raise ValueError(f"Thumbnail slot must be 1 or 2, got {slot}.")
    video_dir = Path(video_dir)
    thumb_dir = get_thumbnails_dir(video_dir)
    for candidate_ext in ALLOWED_THUMBNAIL_EXTS:
        for prefix in ("thumbnail_", "thumb_"):
            _safe_unlink(thumb_dir / f"{prefix}{slot}{candidate_ext}")
            _safe_unlink(video_dir / f"{prefix}{slot}{candidate_ext}")

    manifest_path = video_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        manifest_thumbs = manifest.get("thumbnails", {})
        if str(slot) in manifest_thumbs:
            del manifest_thumbs[str(slot)]
        # Reassign primary if needed
        if manifest_thumbs.get("primary") == str(slot):
            remaining = [s for s in ("1", "2") if s != str(slot) and find_thumbnail_path(video_dir, int(s))]
            manifest_thumbs["primary"] = remaining[0] if remaining else "1"
        write_json(manifest_path, manifest)

    return get_thumbnails(video_dir)


def set_primary_thumbnail(video_dir: Path | str, slot: int) -> dict[str, Any]:
    """Designate slot 1 or 2 as the primary thumbnail variant."""
    if slot not in (1, 2):
        raise ValueError("Slot must be 1 or 2.")
    video_dir = Path(video_dir)
    path = find_thumbnail_path(video_dir, slot)
    if not path or not path.is_file():
        raise FileNotFoundError(f"Thumbnail {slot} does not exist for this video.")

    manifest_path = video_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    manifest_thumbs = manifest.setdefault("thumbnails", {})
    manifest_thumbs["primary"] = str(slot)
    write_json(manifest_path, manifest)
    return get_thumbnails(video_dir)


def get_primary_thumbnail_path(video_dir: Path | str) -> Path | None:
    """Return the filesystem Path of the primary thumbnail, or Thumbnail 1, or Thumbnail 2."""
    video_dir = Path(video_dir)
    data = get_thumbnails(video_dir)
    primary = data.get("primary", "1")
    path = find_thumbnail_path(video_dir, int(primary))
    if path and path.is_file():
        return path
    # Fallback to other slot
    other = 2 if primary == "1" else 1
    path_other = find_thumbnail_path(video_dir, other)
    if path_other and path_other.is_file():
        return path_other
    return None
