"""Local upload -> validate -> render -> publish workflow for supplied assets.

This blueprint runs in the local Flask dashboard. ZIP members are copied individually
after path, type, size, and image validation; the archive is never blindly extracted.
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, render_template, request
from PIL import Image

from pipeline import config
from pipeline.util import read_json

external_workflow_bp = Blueprint("external_workflow", __name__, template_folder="templates")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_REQUEST_BYTES = 300 * 1024 * 1024
_MAX_UNPACKED_BYTES = 450 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 160
_MAX_IMAGE_COUNT = 100
_PLATFORMS = ("youtube", "instagram", "facebook", "x")
_CONNECT_COMMANDS = {
    "youtube": "connect-youtube",
    "facebook": "connect-facebook",
    "x": "connect-x",
    "instagram-drive": "connect-instagram-drive",
}


def _new_workspace(title: str) -> Path:
    from pipeline.util import slugify

    label = slugify(title)[:48] or "external-reel"
    root = config.OUTPUT / "external_inputs" / f"{label}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    (root / "images").mkdir()
    return root


def _extract_images(zip_path: Path, image_dir: Path) -> int:
    """Safely copy image members from a ZIP to the workspace image folder."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("The image upload is not a valid ZIP archive.") from exc

    count = 0
    written_bytes = 0
    seen_names: set[str] = set()
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"The ZIP contains too many files (maximum {_MAX_ARCHIVE_MEMBERS}).")
        declared_size = sum(info.file_size for info in infos if not info.is_dir())
        if declared_size > _MAX_UNPACKED_BYTES:
            raise ValueError("The uncompressed ZIP is too large (maximum 450 MB).")

        for info in infos:
            member_name = info.filename.replace("\\", "/")
            member = PurePosixPath(member_name)
            if member.is_absolute() or ".." in member.parts or not member.parts:
                raise ValueError("The ZIP contains an unsafe path.")
            if info.is_dir():
                continue
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == stat.S_IFLNK:
                raise ValueError("The ZIP contains a symbolic link, which is not allowed.")

            base_name = member.name
            if Path(base_name).suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            if base_name in seen_names:
                raise ValueError(f"The ZIP has duplicate image filename '{base_name}'. Rename the duplicates.")
            if count >= _MAX_IMAGE_COUNT:
                raise ValueError(f"The ZIP contains more than {_MAX_IMAGE_COUNT} images.")

            destination = image_dir / base_name
            copied = 0
            with archive.open(info, "r") as source, destination.open("wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    written_bytes += len(chunk)
                    if written_bytes > _MAX_UNPACKED_BYTES:
                        raise ValueError("The ZIP expands beyond the allowed 450 MB limit.")
                    target.write(chunk)
            if info.file_size and copied == 0:
                destination.unlink(missing_ok=True)
                raise ValueError(f"Image '{base_name}' is empty.")
            try:
                with Image.open(destination) as image:
                    image.verify()
            except Exception as exc:  # noqa: BLE001
                destination.unlink(missing_ok=True)
                raise ValueError(f"'{base_name}' is not a readable image file.") from exc
            seen_names.add(base_name)
            count += 1

    if count == 0:
        raise ValueError("No PNG, JPG, JPEG, or WEBP images were found in the ZIP.")
    return count


def _safe_video_dir(vid: str) -> Path:
    if not vid or Path(vid).name != vid or vid in {".", ".."}:
        abort(400, description="Invalid video ID.")
    root = config.OUTPUT.resolve()
    video_dir = (config.OUTPUT / vid).resolve()
    if video_dir.parent != root:
        abort(400, description="Invalid video ID.")
    if not (video_dir / "script.json").is_file():
        abort(404)
    return video_dir


@external_workflow_bp.get("/external")
def external_page():
    return render_template("external.html", brand=config.BRAND)


@external_workflow_bp.get("/api/external/accounts")
def external_accounts():
    """Expose account setup status only; never return credentials or tokens."""
    youtube = config.YOUTUBE_TOKEN_FILE.is_file()
    instagram = bool((config.INSTAGRAM_ACCESS_TOKEN or config.INSTAGRAM_TOKEN_FILE.is_file()) and config.INSTAGRAM_BUSINESS_ACCOUNT_ID)
    facebook = bool(
        config.FACEBOOK_PAGE_ID
        and (config.FACEBOOK_PAGE_ACCESS_TOKEN or config.FACEBOOK_PAGE_TOKEN_FILE.is_file())
    )
    x_connected = bool(config.X_ACCESS_TOKEN or config.X_TOKEN_FILE.is_file())
    return jsonify({"accounts": [
        {"id": "youtube", "label": "YouTube Shorts", "connected": youtube,
         "hint": "Authorize with Google once." if not youtube else "OAuth token file found."},
        {"id": "instagram", "label": "Instagram Reels", "connected": instagram,
         "hint": "Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env." if not instagram else "API credentials found."},
        {"id": "facebook", "label": "Facebook Reels", "connected": facebook,
         "hint": "Connect a Page and set FACEBOOK_PAGE_ID." if not facebook else "Page credentials found."},
        {"id": "x", "label": "X", "connected": x_connected,
         "hint": "Authorize X once." if not x_connected else "OAuth token file found."},
    ]})


@external_workflow_bp.post("/api/external/connect/<platform>")
def external_connect(platform: str):
    command = _CONNECT_COMMANDS.get(platform)
    if not command:
        return jsonify({"error": "Unknown connection action."}), 400
    from .app import _spawn

    project_root = Path(__file__).resolve().parents[1]

    def job(set_stage):
        set_stage("Opening the account authorization flow")
        result = subprocess.run(
            [sys.executable, str(project_root / "run.py"), command],
            cwd=project_root, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if result.returncode:
            raise RuntimeError((output or f"{command} failed with exit code {result.returncode}")[-2500:])
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        set_stage("done", message=lines[-1] if lines else f"{command} completed.")

    return jsonify({"job": _spawn(job)})


@external_workflow_bp.post("/api/external/render")
def external_render():
    if request.content_length and request.content_length > _MAX_REQUEST_BYTES:
        return jsonify({"error": "Uploads must be smaller than 300 MB combined."}), 413

    script_upload = request.files.get("script")
    zip_upload = request.files.get("images_zip")
    logo_upload = request.files.get("logo")
    if not script_upload or not script_upload.filename:
        return jsonify({"error": "Choose a script.json file."}), 400
    if Path(script_upload.filename).suffix.lower() != ".json":
        return jsonify({"error": "The script file must be JSON (.json)."}), 400
    if not zip_upload or not zip_upload.filename:
        return jsonify({"error": "Choose a ZIP containing the scene images."}), 400
    if Path(zip_upload.filename).suffix.lower() != ".zip":
        return jsonify({"error": "The image bundle must be a .zip file."}), 400
    if logo_upload and logo_upload.filename and Path(logo_upload.filename).suffix.lower() != ".png":
        return jsonify({"error": "The logo must be a PNG file (transparent backgrounds are supported)."}), 400
    # The marker distinguishes an intentionally unchecked UI toggle from older API
    # callers that don't send the new field; those callers keep the default-on behavior.
    if "append_follow_card_present" in request.form:
        append_follow_card = request.form.get("append_follow_card", "").lower() in {"on", "true", "1", "yes"}
    else:
        append_follow_card = request.form.get("append_follow_card", "on").lower() in {"on", "true", "1", "yes"}
    aspect_ratio = (request.form.get("aspect_ratio") or "9:16").strip()
    if aspect_ratio not in {"9:16", "16:9"}:
        return jsonify({"error": "Aspect ratio must be 9:16 or 16:9."}), 400
    render_captions = request.form.get("captions", "on").lower() in {"on", "true", "1", "yes"}

    workspace = None
    try:
        script_bytes = script_upload.read(10 * 1024 * 1024 + 1)
        if len(script_bytes) > 10 * 1024 * 1024:
            raise ValueError("script.json must be smaller than 10 MB.")
        raw_script = json.loads(script_bytes.decode("utf-8-sig"))
        if not isinstance(raw_script, dict):
            raise ValueError("script.json must contain a JSON object.")
        scenes = raw_script.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("script.json must contain a non-empty 'scenes' array.")
        title = str(raw_script.get("title") or raw_script.get("topic") or "external-reel")
        article_url = (
            request.form.get("article_url", "").strip()
            or str(raw_script.get("source_url") or raw_script.get("article_url") or "").strip()
        )
        parsed = urlparse(article_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Add a valid HTTP(S) source/article URL in the form or script.json.")

        workspace = _new_workspace(title)
        # Unique output slugs prevent a rerender from overwriting a same-day video
        # or inheriting another version's publishing history.
        from pipeline.util import slugify
        base_slug = slugify(str(raw_script.get("slug") or title))[:60] or "external-reel"
        raw_script["slug"] = f"{base_slug}-{workspace.name[-8:]}"
        script_path = workspace / "script.json"
        script_path.write_text(json.dumps(raw_script, ensure_ascii=False, indent=2), encoding="utf-8")
        logo_path = None
        if logo_upload and logo_upload.filename:
            logo_path = workspace / "brand-logo.png"
            logo_upload.save(logo_path)
            if logo_path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("The logo must be smaller than 10 MB.")
            try:
                from PIL import Image as PILImage
                with PILImage.open(logo_path) as logo_image:
                    if logo_image.format != "PNG":
                        raise ValueError("The uploaded logo is not a valid PNG image.")
                    logo_image.verify()
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("The uploaded logo is not a valid PNG image.") from exc
        zip_path = workspace / "images-upload.zip"
        zip_upload.save(zip_path)
        image_dir = workspace / "images"
        image_count = _extract_images(zip_path, image_dir)
        zip_path.unlink(missing_ok=True)

        from pipeline.external import load_external_input
        parsed_script, resolved_images, _storyboard_url, parsed_title = load_external_input(script_path, image_dir)
        article_url = article_url or _storyboard_url
        if not article_url:
            raise ValueError("The source article URL is missing.")
    except (ValueError, UnicodeDecodeError, OSError, zipfile.BadZipFile) as exc:
        if workspace and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        if workspace and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400

    from .app import _spawn

    def job(set_stage):
        from pipeline.external import render_external
        set_stage("Validating source and preparing scenes")
        with config.video_format(aspect_ratio):
            set_stage("Rendering voice, captions and video")
            final = render_external(
                article_url, script_path, image_dir,
                render_captions=render_captions,
                append_follow_card=append_follow_card,
                logo_path=logo_path,
            )
        vid = Path(final).parent.name
        set_stage("done", vid=vid, final=f"/media/{vid}/final.mp4",
                  review=f"/v/{vid}", title=parsed_title or parsed_script.topic)

    job_id = _spawn(job)
    return jsonify({
        "job": job_id, "title": parsed_title or parsed_script.topic,
        "scene_count": len(parsed_script.scenes), "image_count": len(resolved_images),
        "follow_end_card": append_follow_card,
        "message": "Assets validated. Rendering has started.",
    })


@external_workflow_bp.get("/api/external/video/<vid>")
def external_video_info(vid: str):
    video_dir = _safe_video_dir(vid)
    script = read_json(video_dir / "script.json")
    article = read_json(video_dir / "article.json") if (video_dir / "article.json").exists() else {}
    return jsonify({
        "vid": vid, "title": script.get("youtube_title") or script.get("topic") or vid,
        "youtube_title": script.get("youtube_title", ""),
        "youtube_description": script.get("youtube_description", ""),
        "instagram_caption": script.get("instagram_caption", ""),
        "tiktok_caption": script.get("tiktok_caption", ""),
        "x_caption": script.get("x_caption", ""),
        "hashtags": script.get("hashtags", []), "source_url": article.get("url") or "",
        "video_url": f"/media/{vid}/final.mp4", "review_url": f"/v/{vid}",
    })


@external_workflow_bp.post("/api/external/publish")
def external_publish():
    data = request.get_json(silent=True) or {}
    vid = str(data.get("vid") or "")
    video_dir = _safe_video_dir(vid)
    video = video_dir / "final.mp4"
    if not video.is_file():
        return jsonify({"error": "Render this video before publishing."}), 400
    if data.get("confirm") is not True:
        return jsonify({"error": "Review the preview and explicitly confirm publishing."}), 400

    requested = data.get("platforms")
    if requested == "all":
        requested = list(_PLATFORMS)
    if not isinstance(requested, list):
        return jsonify({"error": "Choose one or more platforms."}), 400
    platforms = list(dict.fromkeys(str(p).lower() for p in requested))
    if not platforms or any(p not in _PLATFORMS for p in platforms):
        return jsonify({"error": "Supported platforms are YouTube, Instagram, Facebook and X."}), 400
    privacy = str(data.get("privacy_status") or "private").lower()
    if privacy not in {"private", "unlisted", "public"}:
        return jsonify({"error": "YouTube privacy must be private, unlisted, or public."}), 400

    existing = read_json(video_dir / "publishing.json") if (video_dir / "publishing.json").exists() else {}
    already_published = {p for p in platforms if (existing.get(p) or {}).get("status") == "published"}
    to_publish = [p for p in platforms if p not in already_published]
    from .app import _spawn

    def job(set_stage):
        from pipeline.publish import publish
        results = {
            p: {"ok": False, "status": "skipped",
                "message": "Already published; skipped to prevent an accidental duplicate."}
            for p in already_published
        }
        for platform_name in to_publish:
            set_stage(f"Publishing to {platform_name}", publish_results=dict(results))
            try:
                result = publish(
                    video, script_path=video_dir / "script.json",
                    article_path=video_dir / "article.json", platforms=(platform_name,),
                    privacy_status=privacy, confirm=True,
                )
                results[platform_name] = {"ok": True, **(result.get(platform_name) or {})}
            except Exception as exc:  # noqa: BLE001
                results[platform_name] = {"ok": False, "status": "error", "error": str(exc)}
            set_stage(f"Finished {platform_name}", publish_results=dict(results))
        set_stage("done", vid=vid, publish_results=results,
                  message="Publishing attempts finished. Check each platform result below.")

    return jsonify({"job": _spawn(job), "platforms": platforms})


def register_external_routes(app) -> None:
    app.config["MAX_CONTENT_LENGTH"] = max(
        int(app.config.get("MAX_CONTENT_LENGTH") or 0), _MAX_REQUEST_BYTES
    )
    app.register_blueprint(external_workflow_bp)
