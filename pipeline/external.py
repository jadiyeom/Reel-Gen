"""Deterministic render path for externally written scripts and supplied images."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from . import config, state, voice
from .assemble import assemble
from .models import Article, Script, Timeline, TimelineScene
from .util import log, slugify, write_json

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _natural_key(path: Path):
    return [(0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", path.name)]


def _images_in(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
                  key=_natural_key) if folder.exists() else []


def _scene_position(value) -> str | None:
    if value in ("top", "middle", "bottom"):
        return value
    return None


def create_external_workspace(name: str = "") -> Path:
    """Create an input folder with an editable storyboard and image directory."""
    label = name.strip() or f"external-reel-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    slug = slugify(label)
    folder = config.OUTPUT / "external_inputs" / slug
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "images").mkdir()

    scenes = []
    for index in range(1, 7):
        if index == 5:
            scenes.append({
                "index": index, "scene_type": "blank", "narration": "",
                "image_prompt": "", "motion_prompt": "", "hero": False,
            })
        else:
            image_number = index if index < 5 else 5
            scenes.append({
                "index": index, "scene_type": "image",
                "image": f"images/scene_{image_number:02d}.png",
                "narration": f"[Write narration for scene {image_number}]",
                "image_prompt": f"[Describe illustration for scene {image_number}]",
                "motion_prompt": "", "hero": index == 6,
            })

    storyboard = {
        "source_url": "",
        "title": label,
        "topic": label,
        "slug": slug,
        "youtube_title": "[Add title]",
        "youtube_description": "[Add description and source attribution]",
        "tiktok_caption": "[Add TikTok caption]",
        "x_caption": "[Add X caption]",
        "instagram_caption": "[Add Instagram caption]",
        "hashtags": [],
        "scenes": scenes,
    }
    write_json(folder / "script.json", storyboard)
    return folder


def load_external_input(script_path: Path, images_dir: Path | None = None) -> tuple[Script, dict[int, Path], str, str]:
    """Read JSON storyboard or blank-line-separated script and resolve images."""
    script_path = script_path.resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"External script/storyboard not found: {script_path}")
    image_root = (images_dir or (script_path.parent / "images")).resolve()
    available = _images_in(image_root)
    source_url = ""
    supplied_title = ""
    external_scenes = []

    if script_path.suffix.lower() == ".json":
        try:
            data = json.loads(script_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Storyboard JSON is invalid: {exc}") from exc
        source_url = str(data.get("source_url") or data.get("article_url") or "")
        supplied_title = str(data.get("title") or data.get("topic") or "")
        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("Storyboard JSON must contain a non-empty 'scenes' list")
        external_scenes = raw_scenes
    elif script_path.suffix.lower() in (".txt", ".md"):
        text = script_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Script is empty: {script_path}")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        paragraphs = [p for p in paragraphs if not p.startswith("#")]
        for part in paragraphs:
            if part.strip().lower() in ("[blank]", "[pause]", "[blank pause]"):
                external_scenes.append({"scene_type": "blank", "narration": ""})
            else:
                external_scenes.append({"scene_type": "image", "narration": part})
    else:
        raise ValueError("Script input must be .json, .txt, or .md")

    images: dict[int, Path] = {}
    rows = []
    discovered_index = 0
    for order, row in enumerate(external_scenes, 1):
        kind = row.get("scene_type", "image")
        index = int(row.get("index", row.get("scene", order)))
        narration = str(row.get("narration") or "").strip()
        if kind not in ("image", "blank", "image_with_text"):
            raise ValueError(f"Scene {index}: unsupported scene_type '{kind}'")
        prompt = str(row.get("image_prompt") or row.get("visual_direction") or "")
        scene = {
            "index": index, "scene_type": kind, "narration": narration,
            "image_prompt": prompt, "overlay_text": str(row.get("overlay_text") or ""),
            "caption_position": _scene_position(row.get("caption_position")),
            "motion_prompt": str(row.get("motion_prompt") or ""),
            "hero": bool(row.get("hero", False)),
        }
        if kind != "blank":
            supplied = row.get("image") or row.get("image_path")
            image_path = None
            if supplied:
                candidate = Path(str(supplied))
                candidates = [candidate] if candidate.is_absolute() else [script_path.parent / candidate, image_root / candidate]
                for path in candidates:
                    if path.is_file():
                        image_path = path.resolve()
                        break
                if image_path is None:
                    # The storyboard may retain a workspace-relative path while a new image folder is selected.
                    fallback = image_root / Path(str(supplied)).name
                    if fallback.is_file():
                        image_path = fallback.resolve()
            if image_path is None:
                while discovered_index < len(available) and available[discovered_index] in images.values():
                    discovered_index += 1
                if discovered_index < len(available):
                    image_path = available[discovered_index]
                    discovered_index += 1
            if image_path is None:
                raise FileNotFoundError(f"Scene {index} needs an image. Add it to {image_root} or set its 'image' path in the storyboard.")
            images[index] = image_path
            if not narration:
                raise ValueError(f"Scene {index} has an image but no narration")
        rows.append(scene)

    image_count = len(images)
    if not 5 <= image_count <= 100:
        raise ValueError(f"External storyboard must resolve to at least 5 and at most 100 image assets; found {image_count}.")
    # Exact images referenced in a storyboard are allowed in arbitrary JSON order;
    # Script keeps scene order while files are stored under the stable scene index.
    seen = set()
    for row in rows:
        if row["index"] in seen:
            raise ValueError(f"Duplicate scene index: {row['index']}")
        seen.add(row["index"])

    script = Script.model_validate({
        "topic": supplied_title or "Externally authored article short",
        "slug": slugify(str(data.get("slug") or supplied_title or script_path.stem)) if script_path.suffix.lower() == ".json" else slugify(script_path.stem),
        "scenes": rows,
        "youtube_title": str(data.get("youtube_title") or supplied_title or "Article short") if script_path.suffix.lower() == ".json" else supplied_title or "Article short",
        "youtube_description": str(data.get("youtube_description") or "") if script_path.suffix.lower() == ".json" else "",
        "tiktok_caption": str(data.get("tiktok_caption") or "") if script_path.suffix.lower() == ".json" else "",
        "x_caption": str(data.get("x_caption") or "") if script_path.suffix.lower() == ".json" else "",
        "hashtags": list(data.get("hashtags") or []) if script_path.suffix.lower() == ".json" else [],
        "instagram_caption": str(data.get("instagram_caption") or "") if script_path.suffix.lower() == ".json" else "",
    }, context={"allow_extended_storyboard": True})
    narration = " ".join(s.narration for s in script.scenes if s.narration.strip())
    if not narration.strip():
        raise ValueError("External script contains no narration")
    return script, images, source_url, supplied_title


def _article_metadata(url: str, fallback_title: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("--article-url must be a valid http(s) URL")
    try:
        from .articles import extract
        article = extract(url)
        return {"url": article.url, "title": article.title or fallback_title,
                "site_name": article.site_name or parsed.hostname.removeprefix("www."),
                "author": article.author, "published": article.published,
                "content": article.content, "content_hash": article.content_hash}
    except Exception as exc:  # noqa: BLE001
        # External creative assets are authoritative; network extraction only enriches attribution.
        log(f"article metadata extraction unavailable ({exc}); using URL domain for source attribution")
        return {"url": url, "title": fallback_title,
                "site_name": parsed.hostname.removeprefix("www."), "author": "", "published": ""}


def render_external(
    article_url: str,
    script_path: Path,
    images_dir: Path | None = None,
    render_captions: bool = True,
    append_follow_card: bool = True,
    logo_path: Path | None = None,
) -> Path:
    if config.GENERATION_MODE != "external":
        raise RuntimeError("render-external requires GENERATION_MODE=external")
    script, source_images, storyboard_url, title = load_external_input(script_path, images_dir)
    url = article_url or storyboard_url
    if not url:
        raise ValueError("Article URL is required for source attribution")
    article = _article_metadata(url, title or script.topic)
    output_slug = script.slug if config.ASPECT_RATIO == "9:16" else f"{script.slug}-16x9"
    video = state.Video(output_slug)
    video.manifest["aspect_ratio"] = config.ASPECT_RATIO
    video.manifest["extended_storyboard"] = len(script.scenes) > 12 or len(source_images) > 8
    saved_images: dict[int, Path] = {}
    for scene in script.scenes:
        dest = video.scenes_dir / f"scene_{scene.index:02d}.png"
        if scene.scene_type == "blank":
            Image.new("RGB", (config.WIDTH, config.HEIGHT), (244, 233, 210)).save(dest)
        else:
            source = source_images[scene.index]
            dest = video.scenes_dir / f"scene_{scene.index:02d}{source.suffix.lower()}"
            shutil.copy2(source, dest)
        saved_images[scene.index] = dest
    video.manifest["article"] = article
    video.manifest["generation_mode"] = "external"
    video.manifest["script_path"] = str(Path(script_path).resolve())
    video.manifest["illustrations"] = {str(k): str(v) for k, v in saved_images.items()}
    write_json(video.script_path, script.model_dump())
    write_json(video.dir / "script.json", script.model_dump())
    write_json(video.dir / "article.json", article)

    audio_info = voice.synthesize(video.audio_dir, script)
    cursor = 0.0
    timeline_rows = []
    for scene, audio in zip(script.scenes, audio_info):
        end = cursor + float(audio["duration"])
        timeline_rows.append(TimelineScene(index=scene.index, scene_type=scene.scene_type,
                                           start=round(cursor, 3), end=round(end, 3),
                                           narration=scene.narration))
        cursor = end
    write_json(video.dir / "timeline.json", Timeline(scenes=timeline_rows, duration=round(cursor, 3)).model_dump())
    video.manifest["stages"] = {"script":{"done":True}, "images":{"done":True,"count":len(source_images)},
                                "voice":{"done":True}, "timeline":{"done":True}, "render":{"done":False}}
    video.save()
    state.record_video(video, script.topic, "rendering")
    final = assemble(video, script, saved_images, audio_info, want_captions=render_captions)
    if append_follow_card:
        from .end_card import append_follow_card_to_video

        final = append_follow_card_to_video(final, logo_path=logo_path)
    video.manifest["follow_end_card"] = bool(append_follow_card)
    video.mark("complete", final=str(final))
    state.record_video(video, script.topic, "complete")
    if config.AUTO_PUBLISH_PLATFORMS:
        from .publish import auto_publish
        auto_publish(final)
    log(f"external reel -> {final}")
    return final
