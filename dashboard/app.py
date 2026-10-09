"""Review dashboard for the AI short-form video pipeline.

- Home: produced videos, preview + per-platform captions + download.
- Library: every generated image/animation in the catalog.
- Create: a guided workflow — write the script, approve or regenerate with your
  notes, then produce the video (background job with live status).
- Music selector: pick a track and fit it over an existing video.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from pipeline import config, drafts, library, scriptgen, state
from pipeline.util import read_json, slugify

app = Flask(__name__, template_folder="templates", static_folder="static")
JOBS: dict[str, dict] = {}

_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")


def _spawn(fn) -> str:
    """Run fn(set_stage) in a background thread; return a job id to poll."""
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"stage": "queued", "vid": None, "error": None, "progress": []}

    def _run():
        try:
            def set_stage(s, **kw):
                job = JOBS[job_id]
                job.update(stage=s, **kw)
                if s not in ("queued", "error", "done") and s not in job["progress"]:
                    job["progress"].append(s)
            fn(set_stage)
            JOBS[job_id].setdefault("stage", "done")
            if JOBS[job_id]["stage"] not in ("done", "error"):
                JOBS[job_id]["stage"] = "done"
        except Exception as e:  # noqa: BLE001
            JOBS[job_id].update(stage="error", error=str(e))

    threading.Thread(target=_run, daemon=True).start()
    return job_id


# ---------- helpers ----------
def _videos() -> list[dict]:
    items = []
    if config.OUTPUT.exists():
        for d in sorted(config.OUTPUT.iterdir(), reverse=True):
            if (d / "script.json").exists() and (d / "final.mp4").exists():
                data = read_json(d / "script.json")
                items.append({"id": d.name, "topic": data.get("topic", d.name),
                              "title": data.get("youtube_title", "")})
    return items


def _video_obj(vid: str):
    d = config.OUTPUT / vid
    if not (d / "script.json").exists():
        abort(404)
    return state.Video(vid[11:], vid[:10])   # {YYYY-MM-DD}-{slug}


def _music_files() -> list[str]:
    return sorted(f.name for f in config.MUSIC_DIR.iterdir()
                  if f.suffix.lower() in _AUDIO_EXTS) if config.MUSIC_DIR.exists() else []


# ---------- pages ----------
@app.route("/")
def index():
    videos = _videos()
    vids = {v["id"] for v in videos}
    all_drafts = drafts.list_drafts()
    # "In-progress" = work that isn't a finished, still-present video. A draft whose
    # produced video already exists belongs under Videos, not the drafts shelf.
    in_progress = [d for d in all_drafts
                   if not (d.get("stage") == "produced" and d.get("vid") in vids)]
    draft_by_vid = {d["vid"]: d["id"] for d in all_drafts if d.get("vid")}
    return render_template("index.html", videos=videos, drafts=in_progress,
                           draft_by_vid=draft_by_vid, brand=config.BRAND)


@app.get("/api/drafts")
def api_drafts():
    return jsonify(drafts.list_drafts())


@app.get("/api/draft/<draft_id>")
def api_draft_get(draft_id: str):
    d = drafts.load(draft_id)
    return jsonify(d) if d else (jsonify({"error": "not found"}), 404)


@app.post("/api/draft/save")
def api_draft_save():
    return jsonify({"id": drafts.save(request.get_json(force=True))})


@app.post("/api/draft/delete")
def api_draft_delete():
    return jsonify({"ok": drafts.delete(request.get_json(force=True).get("id", ""))})


@app.route("/v/<vid>")
def video(vid: str):
    d = config.OUTPUT / vid
    if not (d / "script.json").exists():
        abort(404)
    s = read_json(d / "script.json")
    manifest = read_json(d / "manifest.json") if (d / "manifest.json").exists() else {}
    return render_template("video.html", vid=vid, s=s, brand=config.BRAND,
                           aspect_ratio=manifest.get("aspect_ratio", "9:16"),
                           music=_music_files(), current_music=manifest.get("music", ""),
                           current_volume=manifest.get("music_volume", 0.16))


@app.route("/library")
def library_page():
    clips = library.all_clips()
    groups = sorted({c["grp"] for c in clips})
    return render_template("library.html", clips=clips, groups=groups,
                           stats=library.stats(), brand=config.BRAND)


@app.route("/create")
def create_page():
    return render_template("create.html", brand=config.BRAND)


# ---------- media ----------
@app.route("/media/<vid>/final.mp4")
def media(vid: str):
    f = config.OUTPUT / vid / "final.mp4"
    return send_file(f, mimetype="video/mp4", conditional=True) if f.exists() else abort(404)


@app.route("/media/scenes/<vid>/<int:index>.png")
def media_scene(vid: str, index: int):
    f = config.OUTPUT / vid / "scenes" / f"scene_{index:02d}.png"
    return send_file(f, mimetype="image/png", conditional=True) if f.exists() else abort(404)


@app.route("/download/<vid>")
def download(vid: str):
    f = config.OUTPUT / vid / "final.mp4"
    return send_file(f, as_attachment=True, download_name=f"{vid}.mp4") if f.exists() else abort(404)


@app.route("/media/music/<path:name>")
def media_music(name: str):
    f = config.MUSIC_DIR / Path(name).name
    return send_file(f, conditional=True) if f.exists() else abort(404)


@app.route("/media/preview/<vid>")
def media_preview(vid: str):
    from pipeline.assemble import build_preview_base
    try:
        f = build_preview_base(_video_obj(vid))
    except FileNotFoundError:
        abort(404)
    return send_file(f, mimetype="video/mp4", conditional=True)


@app.route("/media/lib/<cid>.mp4")
def lib_clip(cid: str):
    f = config.LIB_CLIPS / f"{cid}.mp4"
    return send_file(f, mimetype="video/mp4", conditional=True) if f.exists() else abort(404)


@app.route("/media/libimg/<cid>")
def lib_img(cid: str):
    for ext in (".jpg", ".png"):
        f = config.LIB_IMAGES / f"{cid}{ext}"
        if f.exists():
            return send_file(f, conditional=True)
    abort(404)


# ---------- workflow API ----------
@app.post("/api/script")
def api_script():
    data = request.get_json(force=True)
    topic = (data.get("topic") or "").strip()   # blank => auto-pick a topic
    if data.get("target"):
        config.TARGET_SECONDS = int(data["target"])
    with config.video_format(data.get("aspect_ratio", "9:16")):
        script = scriptgen.generate(topic, instruction=data.get("instruction", ""))
    return jsonify(script.model_dump())


@app.post("/api/article/script")
def api_article_script():
    from pipeline.articles import create
    data = request.get_json(force=True)
    url = (data.get("article_url") or "").strip()
    if not url:
        return jsonify({"error": "article_url required"}), 400
    try:
        with config.video_format(data.get("aspect_ratio", "9:16")):
            result = create(url, instruction=data.get("instruction", ""))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 400
    script = result.script.model_dump()
    script["article_url"] = result.article.url
    script["content_analysis"] = result.analysis.model_dump()
    return jsonify(script)


@app.post("/api/match")
def api_match():
    """Preview which library clip each scene will use, with swap candidates."""
    from pipeline import match
    from pipeline.models import Script

    script = Script(**request.get_json(force=True)["script"])
    used: set[str] = set()
    scenes = []
    for sc in script.scenes:
        if sc.scene_type == "blank":
            scenes.append({"index": sc.index, "narration": sc.narration,
                           "image_prompt": "", "chosen": None, "auto_score": 0,
                           "candidates": []})
            continue
        clip, score = match.match_scene(sc, used)
        cands = match.candidates(sc.image_prompt, used)
        chosen = clip["id"] if clip else (cands[0]["id"] if cands else None)
        if chosen:
            used.add(chosen)
        scenes.append({"index": sc.index, "narration": sc.narration,
                       "image_prompt": sc.image_prompt, "chosen": chosen,
                       "auto_score": round(score, 3), "candidates": cands})
    return jsonify({"scenes": scenes})


@app.post("/api/produce")
def api_produce():
    from pipeline.models import Script
    from pipeline.produce import make

    data = request.get_json(force=True)
    topic = data.get("topic", "")
    script = Script(**data["script"])
    clips = {str(k): v for k, v in (data.get("clips") or {}).items() if v}
    draft_id = data.get("draft")

    def job(set_stage):
        if data.get("voice"):
            config.TTS_VOICE = data["voice"]
        if data.get("tempo"):
            config.SPEECH_TEMPO = float(data["tempo"])
        with config.video_format(data.get("aspect_ratio", "9:16")):
            final = make(topic, script=script, on_stage=lambda s: set_stage(s), clip_overrides=clips,
                         article_url=data.get("article_url") or None)
        vid = Path(final).parent.name
        if draft_id:
            d = drafts.load(draft_id)
            if d:
                d.update(stage="produced", vid=vid)
                drafts.save(d)
        set_stage("done", vid=vid)

    return jsonify({"job": _spawn(job)})


@app.post("/api/video/<vid>/scene/<int:index>/regenerate")
def api_regenerate_scene(vid: str, index: int):
    from pipeline import images
    from pipeline.models import Script
    video_obj = _video_obj(vid)
    script = Script.model_validate(read_json(video_obj.script_path), context={
        "allow_extended_storyboard": bool(video_obj.manifest.get("extended_storyboard"))})
    scene = next((s for s in script.scenes if s.index == index), None)
    if not scene or scene.scene_type == "blank":
        return jsonify({"error": "illustration scene not found"}), 404
    prompt = (request.get_json(silent=True) or {}).get("image_prompt", scene.image_prompt).strip()
    if not prompt:
        return jsonify({"error": "image_prompt required"}), 400
    scene.image_prompt = prompt
    out = video_obj.scenes_dir / f"scene_{index:02d}.png"
    try:
        aspect_ratio = video_obj.manifest.get("aspect_ratio", "9:16")
        with config.video_format(aspect_ratio):
            article_style = bool((video_obj.manifest.get("article") or {}).get("article"))
            style_path = config.PROMPTS / config.ILLUSTRATION_STYLE
            style = style_path.read_text(encoding="utf-8") if article_style and style_path.exists() else None
            if style:
                style = style.replace("{{composition_instruction}}", config.composition_instruction())
            images.generate_image(prompt, out, style=style)
            import hashlib
            used_style = (style or config.IMAGE_STYLE) + config.composition_instruction()
            fingerprint = hashlib.sha256((prompt + used_style + f"|{config.WIDTH}x{config.HEIGHT}").encode()).hexdigest()
            out.with_suffix(".sha256").write_text(fingerprint, encoding="utf-8")
            write_json(video_obj.script_path, script.model_dump())
            video_obj.manifest.setdefault("illustrations", {})[str(index)] = {"prompt": prompt, "regenerated": True}
            video_obj.save()
            from pipeline.assemble import refresh_scene
            refresh_scene(video_obj, script, index)
        return jsonify({"ok": True, "path": f"/media/scenes/{vid}/{index}.png", "video": f"/media/{vid}/final.mp4"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    return jsonify(JOBS.get(job_id, {"stage": "unknown"}))


# ---------- inventory management ----------
@app.post("/api/library/fetch")
def api_library_fetch():
    """Add clips by fetching stock footage for a query (free)."""
    from pipeline import stock

    data = request.get_json(force=True)
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query required"}), 400
    row = {"id": f"stock_{slugify(query)[:28]}", "group": data.get("group", "custom"),
           "lighting": "", "query": query, "description": data.get("description") or query}
    n = int(data.get("n", 5))

    def job(set_stage):
        set_stage(f"fetching '{query}'")
        stock.fetch_variants(row, n)

    return jsonify({"job": _spawn(job)})


@app.post("/api/library/generate")
def api_library_generate():
    """Add a clip by AI-generating it (Flux + Wan) — costs fal credit."""
    from pipeline import animate, images, library as lib
    from pipeline.assemble import _prepare_motion  # noqa: F401 (ensure module ok)

    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    motion = data.get("motion", "")
    group = data.get("group", "generated")

    def job(set_stage):
        cid = f"gen_{slugify(prompt)[:24]}"
        img = config.LIB_IMAGES / f"{cid}.png"
        set_stage("generating image")
        url = images.generate_image(prompt, img)
        set_stage("animating")
        raw = config.LIB_CLIPS / f"{cid}_raw.mp4"
        animate.i2v(img, url, motion, raw)
        clip = config.LIB_CLIPS / f"{cid}.mp4"
        from pipeline.produce import _normalize_clip
        _normalize_clip(raw, clip)
        raw.unlink(missing_ok=True)
        from pipeline.util import ffprobe_duration
        row = {"id": cid, "group": group, "lighting": "", "style": "generated",
               "description": prompt, "image_prompt": prompt, "motion_prompt": motion}
        lib.add_clip(row, img, clip, ffprobe_duration(clip), lib.embed(prompt))

    return jsonify({"job": _spawn(job)})


# ---------- video / music management ----------
@app.post("/api/video/delete")
def api_video_delete():
    import shutil
    vid = request.get_json(force=True).get("vid", "")
    d = config.OUTPUT / vid
    if d.exists() and d.parent == config.OUTPUT:
        shutil.rmtree(d, ignore_errors=True)
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@app.post("/api/music/delete")
def api_music_delete():
    name = request.get_json(force=True).get("name", "")
    f = config.MUSIC_DIR / Path(name).name
    if f.exists():
        f.unlink()
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@app.get("/api/clips")
def api_clips():
    """All clips (for the visual picker): id, description, group."""
    return jsonify([{"id": c["id"], "description": c["description"], "grp": c["grp"]}
                    for c in library.all_clips()])


@app.post("/api/clip/delete")
def api_clip_delete():
    cid = request.get_json(force=True).get("id", "")
    return jsonify({"ok": library.delete_clip(cid)})


@app.post("/api/clip/update")
def api_clip_update():
    data = request.get_json(force=True)
    return jsonify({"ok": library.update_description(data.get("id", ""), data.get("description", ""))})


@app.get("/api/music")
def api_music():
    return jsonify({"tracks": _music_files()})


@app.post("/api/remix")
def api_remix():
    from pipeline.assemble import remix_music

    data = request.get_json(force=True)
    video = _video_obj(data["vid"])
    track = data.get("music") or ""
    music_path = (config.MUSIC_DIR / track) if track else None
    if music_path and not music_path.exists():
        return jsonify({"error": "track not found"}), 400
    remix_music(video, music_path,
                volume=float(data.get("volume", 0.16)),
                start=float(data.get("start", 0.0)))
    return jsonify({"ok": True})


@app.post("/api/upload-music")
def api_upload_music():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(_AUDIO_EXTS):
        return jsonify({"error": "audio file required"}), 400
    dest = config.MUSIC_DIR / Path(f.filename).name
    f.save(dest)
    return jsonify({"ok": True, "name": dest.name})


def run_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    print(f"\nShorts Studio -> http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
