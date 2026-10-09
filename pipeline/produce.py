"""End-to-end production of one video: visuals (library match -> generate on miss),
voice, captions, music, outro, assembly. Shared by the CLI and the dashboard.
"""
from __future__ import annotations

from pathlib import Path
import hashlib

from . import animate, cards, config, images as imggen, library, match, scriptgen, state, voice
from .assemble import assemble
from .models import Script, Timeline, TimelineScene
from .util import ffprobe_duration, log, run as run_cmd, step, write_json


def _normalize_clip(src: Path, dst: Path) -> None:
    vf = (f"scale={config.WIDTH}:{config.HEIGHT}:force_original_aspect_ratio=increase,"
          f"crop={config.WIDTH}:{config.HEIGHT},fps={config.FPS},setsar=1,format=yuv420p")
    run_cmd(["ffmpeg", "-y", "-i", str(src), "-an", "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(dst)])


def _generate_and_store(scene, video, images: dict, motion: dict, article_mode: bool = False) -> None:
    """Miss path: generate an image (+animation) and add it to the library."""
    img = video.scenes_dir / f"scene_{scene.index:02d}.png"
    style = config.IMAGE_STYLE
    if article_mode:
        style_path = config.PROMPTS / config.ILLUSTRATION_STYLE
        style = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
    composition = config.composition_instruction()
    style = style.replace("{{composition_instruction}}", composition)
    if composition not in style:
        style = f"{style}\n{composition}"
    fingerprint = hashlib.sha256((scene.image_prompt + style + f"|{config.WIDTH}x{config.HEIGHT}").encode()).hexdigest()
    marker = img.with_suffix(".sha256")
    if img.exists() and marker.exists() and marker.read_text(encoding="utf-8") == fingerprint:
        images[scene.index] = img
        log(f"scene {scene.index}: illustration cache hit")
        return
    try:
        if config.IMAGE_BACKEND == "fal" and not config.FAL_KEY:
            raise RuntimeError("FAL_KEY is not configured")
        url = imggen.generate_image(scene.image_prompt, img, style=style if article_mode else None)
        marker.write_text(fingerprint, encoding="utf-8")
        images[scene.index] = img
        if config.ANIMATE != "none" and config.FAL_KEY:
            raw = video.scenes_dir / f"scene_{scene.index:02d}_raw.mp4"
            animate.i2v(img, url, scene.motion_prompt, raw)
            cid = f"gen_{video.slug}_{scene.index:02d}"
            clip = config.LIB_CLIPS / f"{cid}.mp4"
            _normalize_clip(raw, clip)
            raw.unlink(missing_ok=True)
            row = {"id": cid, "group": "generated", "lighting": "", "style": "",
                   "description": scene.image_prompt, "image_prompt": scene.image_prompt,
                   "motion_prompt": scene.motion_prompt}
            library.add_clip(row, img, clip, ffprobe_duration(clip),
                             library.embed(scene.image_prompt))
            motion[scene.index] = clip
            log(f"scene {scene.index}: generated + added to library ({cid})")
        else:
            log(f"scene {scene.index}: generated still (Ken Burns)")
    except Exception as e:  # noqa: BLE001
        if article_mode:
            raise RuntimeError(f"scene {scene.index} illustration generation failed: {e}") from e
        log(f"scene {scene.index}: generation failed ({e}); fallback background")
        cards.render_fallback_bg(img)
        images[scene.index] = img


def build_visuals(video, script: Script, on_stage=None, overrides: dict | None = None,
                  article_mode: bool = False):
    step("Visuals (library match -> generate on miss)")
    overrides = overrides or {}
    images: dict[int, Path] = {}
    motion: dict[int, Path] = {}
    used_ids: set[str] = set()
    scene_clips: dict[str, str] = {}
    for scene in script.scenes:
        if on_stage:
            on_stage(f"scene {scene.index}/{len(script.scenes)} visuals")
        if scene.scene_type == "blank":
            from PIL import Image
            img = video.scenes_dir / f"scene_{scene.index:02d}.png"
            Image.new("RGB", (config.WIDTH, config.HEIGHT), (245, 241, 232)).save(img)
            images[scene.index] = img
            continue
        # explicit user choice (preview/swap) wins
        chosen = None if article_mode else (overrides.get(scene.index) or overrides.get(str(scene.index)))
        if chosen:
            clip = library.get_clip(chosen)
            if clip and Path(clip["video_path"]).exists():
                motion[scene.index] = Path(clip["video_path"])
                library.mark_used(clip["id"], video.slug)
                used_ids.add(clip["id"])
                scene_clips[str(scene.index)] = clip["id"]
                log(f"scene {scene.index}: chosen {clip['id']}")
                continue
        clip, score = (None, 0.0) if article_mode else match.match_scene(scene, used_ids)
        if clip and Path(clip["video_path"]).exists():
            motion[scene.index] = Path(clip["video_path"])
            library.mark_used(clip["id"], video.slug)
            used_ids.add(clip["id"])
            scene_clips[str(scene.index)] = clip["id"]
            log(f"scene {scene.index}: reuse {clip['id']} (match {score:.2f})")
        else:
            log(f"scene {scene.index}: no match (best {score:.2f}) -> generate")
            _generate_and_store(scene, video, images, motion, article_mode=article_mode)
    video.manifest["scene_clips"] = scene_clips
    video.save()
    return images, motion


def make(topic: str | None, script: Script | None = None, on_stage=None,
         clip_overrides: dict | None = None, article_url: str | None = None) -> Path:
    article_result = None
    if article_url and script is None:
        from .articles import create
        article_result = create(article_url, on_stage=on_stage)
        script = article_result.script
        topic = article_result.analysis.strongest_idea
    elif article_url:
        from .articles import extract
        article_result = extract(article_url)
        if on_stage:
            on_stage("Article extracted")
    topic = topic or state.next_topic() or config.DEFAULT_TOPIC
    script = script or scriptgen.generate(topic)
    if on_stage:
        on_stage("Script generated")
    if on_stage and article_url:
        on_stage("Storyboard created")
    output_slug = script.slug if config.ASPECT_RATIO == "9:16" else f"{script.slug}-16x9"
    video = state.Video(output_slug)
    video.manifest["aspect_ratio"] = config.ASPECT_RATIO
    script_digest = hashlib.sha256(script.model_dump_json().encode()).hexdigest()
    previous_digest = video.manifest.get("script_hash")
    if previous_digest and previous_digest != script_digest:
        # Cached scene audio is keyed by exact narration, not only the script slug.
        for audio in video.audio_dir.glob("scene_*"):
            if audio.suffix.lower() in (".mp3", ".wav", ".sha256"):
                audio.unlink(missing_ok=True)
    video.manifest["script_hash"] = script_digest
    if article_result:
        video.manifest["article"] = article_result.model_dump(mode="json")
    write_json(video.script_path, script.model_dump())
    state.record_video(video, topic, "generating")

    images, motion = build_visuals(video, script, on_stage=on_stage, overrides=clip_overrides,
                                   article_mode=bool(article_url))
    if on_stage and article_url:
        on_stage(f"{sum(s.scene_type != 'blank' for s in script.scenes)} illustrations generated")
    audio_info = voice.synthesize(video.audio_dir, script)
    if on_stage:
        on_stage("Voice generated")
    # TTS clips are the timing master: each distinct scene uses its actual spoken
    # clip duration, preserving pauses rather than distributing time evenly.
    cursor = 0.0
    timeline_scenes = []
    for scene, audio in zip(script.scenes, audio_info):
        end = cursor + float(audio["duration"])
        timeline_scenes.append(TimelineScene(index=scene.index, scene_type=scene.scene_type,
                                             start=round(cursor, 3), end=round(end, 3),
                                             narration=scene.narration))
        cursor = end
    timeline = Timeline(scenes=timeline_scenes, duration=round(cursor, 3))
    write_json(video.dir / "timeline.json", timeline.model_dump())
    video.manifest["timeline"] = str(video.dir / "timeline.json")
    if on_stage:
        on_stage("Audio synchronized")
    final = assemble(video, script, images, audio_info,
                     motion_clips=motion, want_captions=True)

    video.mark("complete", final=str(final))
    if on_stage:
        on_stage("Video rendered")
    state.record_video(video, topic, "complete")
    if config.AUTO_PUBLISH_PLATFORMS:
        from .publish import auto_publish
        auto_publish(final)
    if on_stage:
        on_stage("done")
    return final
