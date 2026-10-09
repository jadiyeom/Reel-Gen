"""Assemble the final 1080x1920 MP4 (v2, image-first).

Per scene: an animated i2v clip (stretched to the narration length) or, if a scene
isn't animated, varied Ken Burns on its still. Scenes are hard-cut together, a
static logo+disclaimer watermark is overlaid (it does NOT zoom with the footage),
karaoke captions are burned over everything, and the prebuilt branded outro is
stitched on the end.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .models import Script
from .util import ffprobe_duration, log, run, step

FPS = config.FPS
W, H = config.WIDTH, config.HEIGHT
_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

# Ken Burns motion presets (zoom/pan expressions over a 2x-prescaled still).
_KB = {
    "in":        "z='min(zoom+0.0011,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "out":       "z='if(eq(on,0),1.20,max(zoom-0.0011,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "pan_right": "z=1.14:x='(iw-iw/zoom)*on/{F}':y='ih/2-(ih/zoom/2)'",
    "pan_left":  "z=1.14:x='(iw-iw/zoom)*(1-on/{F})':y='ih/2-(ih/zoom/2)'",
    "pan_up":    "z=1.14:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{F})'",
    "pan_down":  "z=1.14:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{F}'",
}


def _ass_path_escape(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:")


def _ken_burns(image: Path, dur: float, out: Path, preset: str) -> None:
    frames = max(1, int(round(dur * FPS)))
    motion = _KB.get(preset, _KB["in"]).format(F=frames)
    vf = (
        f"scale={W * 2}:{H * 2}:flags=lanczos,"
        f"zoompan={motion}:d={frames}:s={W}x{H}:fps={FPS},"
        f"setsar=1,format=yuv420p"
    )
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", f"{dur:.3f}",
         "-filter_complex", vf, "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])


def _prepare_motion(clip: Path, dur: float, out: Path) -> None:
    """Cover-fit an i2v clip to 1080x1920 and time-stretch it to the scene length."""
    src = max(0.2, ffprobe_duration(clip))
    ratio = dur / src                      # >1 slows the clip to fill the scene
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"setpts={ratio:.4f}*PTS,fps={FPS},setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-i", str(clip), "-filter_complex", vf, "-an",
         "-t", f"{dur:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])


def _concat(clips: list[Path], out: Path, work: Path, name: str = "concat.txt") -> None:
    listing = work / name
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(out)])


def _overlay_watermark(body: Path, watermark: Path, out: Path) -> None:
    # -loop 1 keeps the watermark on EVERY frame; shortest=1 ends with the video.
    run(["ffmpeg", "-y", "-i", str(body), "-loop", "1", "-i", str(watermark),
         "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:shortest=1[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])


def _padded_narration(audio_info: list[dict], work: Path) -> tuple[Path, float]:
    parts: list[Path] = []
    total = 0.0
    for info in audio_info:
        dur = float(info["duration"])
        total += dur
        seg = work / f"nar_{info['index']:02d}.wav"
        run(["ffmpeg", "-y", "-i", info["path"], "-af", "aresample=44100,apad",
             "-t", f"{dur:.3f}", "-ar", "44100", "-ac", "2", str(seg)])
        parts.append(seg)
    out = work / "narration_full.wav"
    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p)]
    streams = "".join(f"[{i}:a]" for i in range(len(parts)))
    run(["ffmpeg", "-y", *inputs, "-filter_complex",
         f"{streams}concat=n={len(parts)}:v=0:a=1[a]", "-map", "[a]", str(out)])
    return out, total


def _find_music() -> Path | None:
    import random
    tracks = [f for f in (config.MUSIC_DIR.iterdir() if config.MUSIC_DIR.exists() else [])
              if f.suffix.lower() in _AUDIO_EXTS]
    return random.choice(tracks) if tracks else None


def _build_audio(narration: Path, total: float, content_dur: float,
                 music: Path | None, out: Path,
                 music_volume: float = 0.16, music_start: float = 0.0) -> None:
    """Speech = narration (content) + the outro voiceover placed over the outro,
    with an optional ducked music bed under everything. music_volume/music_start
    let the dashboard 'fit' a chosen track over the video."""
    delay = int(round((content_dur + 0.3) * 1000))   # outro VO starts just into the outro
    has_vo = config.ENABLE_OUTRO and config.OUTRO_VO.exists()

    inputs = ["-i", str(narration)]
    if has_vo:
        inputs += ["-i", str(config.OUTRO_VO)]
        speech = (f"[0:a]apad=whole_dur={total:.3f}[nar];"
                  f"[1:a]adelay={delay}|{delay}[ov];"
                  f"[nar][ov]amix=inputs=2:normalize=0[speech];")
        mus_idx = 2
    else:
        speech = f"[0:a]apad=whole_dur={total:.3f}[speech];"
        mus_idx = 1

    if music:
        log(f"music bed: {music.name} (vol={music_volume}, start={music_start}s)")
        inputs += ["-i", str(music)]
        flt = (speech +
               f"[speech]asplit=2[s1][s2];"
               f"[{mus_idx}:a]aloop=loop=-1:size=2000000000,"
               f"atrim={music_start:.2f}:{music_start + total:.3f},asetpts=N/SR/TB,"
               f"volume={music_volume:.3f},afade=t=out:st={max(0, total-1.5):.3f}:d=1.5[m];"
               f"[m][s1]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=350[duck];"
               f"[duck][s2]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        log("no music track in assets/music — voice only")
        flt = speech + "[speech]loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    run(["ffmpeg", "-y", *inputs, "-filter_complex", flt, "-map", "[a]",
         "-t", f"{total:.3f}", "-ar", "44100", "-ac", "2", str(out)])


def _build_outro_clip() -> tuple[Path | None, float]:
    """Build the optional outro clip + its voiceover. Returns (clip, duration), or
    (None, 0.0) when the outro is disabled (OUTRO=false) or fails to render."""
    if not config.ENABLE_OUTRO:
        return None, 0.0
    try:
        from .outro import build_outro, build_outro_vo
        clip = build_outro()
        build_outro_vo()
        return clip, ffprobe_duration(clip)
    except Exception as e:  # noqa: BLE001
        log(f"outro skipped ({e})")
        return None, 0.0


def _outro_seconds() -> float:
    """Duration the already-rendered visuals reserve for the outro (0 if disabled)."""
    if config.ENABLE_OUTRO and config.PREBUILT_OUTRO.exists():
        return ffprobe_duration(config.PREBUILT_OUTRO)
    return 0.0


def assemble(video, script: Script, scene_images: dict[int, Path],
             audio_info: list[dict], motion_clips: dict[int, Path] | None = None,
             want_captions: bool = True) -> Path:
    step("Assemble")
    work = video.dir / "work"
    work.mkdir(exist_ok=True)
    motion_clips = motion_clips or {}
    dur_by_idx = {a["index"]: float(a["duration"]) for a in audio_info}

    # Per-scene clips: animated i2v (stretched) or varied Ken Burns.
    scene_clips: list[Path] = []
    for i, scene in enumerate(script.scenes):
        clip = work / f"clip_{scene.index:02d}.mp4"
        dur = dur_by_idx[scene.index]
        if scene.index in motion_clips:
            _prepare_motion(motion_clips[scene.index], dur, clip)
            log(f"motion scene {scene.index} ({dur:.2f}s)")
        else:
            preset = config.KEN_BURNS_CYCLE[i % len(config.KEN_BURNS_CYCLE)]
            _ken_burns(scene_images[scene.index], dur, clip, preset)
            log(f"ken burns ({preset}) scene {scene.index} ({dur:.2f}s)")
        scene_clips.append(clip)

    body = work / "body.mp4"
    _concat(scene_clips, body, work, "scenes.txt")

    # Optional static watermark (logo bottom-right + disclaimer) — overlaid so it
    # never zooms. Skipped if disabled, if there's nothing to show, or if it fails.
    body_branded = body
    if config.ENABLE_WATERMARK:
        try:
            from .cards import render_watermark
            if not config.WATERMARK_PNG.exists():
                render_watermark()
            if config.WATERMARK_PNG.exists():
                body_branded = work / "body_branded.mp4"
                _overlay_watermark(body, config.WATERMARK_PNG, body_branded)
        except Exception as e:  # noqa: BLE001
            log(f"watermark skipped ({e})")
            body_branded = body

    # Audio + captions over the whole content.
    narration, content_dur = _padded_narration(audio_info, work)
    ass_path = None
    if want_captions:
        from . import captions
        true_text = " ".join(s.narration.strip() for s in script.scenes)
        cursor = 0.0
        position_ranges = []
        for scene, info in zip(script.scenes, audio_info):
            duration = float(info["duration"])
            if scene.narration.strip():
                position_ranges.append({"start": cursor, "end": cursor + duration,
                                        "position": scene.caption_position or config.CAPTION_POSITION})
            cursor += duration
        ass_path = captions.generate(narration, video.dir / "captions.ass", true_text=true_text,
                                     position_ranges=position_ranges)

    source_ass = _source_ass(video)

    # Optional branded outro (+ its voiceover), stitched on the end.
    outro, outro_dur = _build_outro_clip()
    visuals = work / "visuals.mp4"
    if outro:
        _concat([body_branded, outro], visuals, work, "final_concat.txt")
    else:
        run(["ffmpeg", "-y", "-i", str(body_branded), "-c", "copy", str(visuals)])

    total = content_dur + outro_dur
    audio_full = work / "audio_full.wav"
    music = _find_music()
    if music:
        video.manifest["music"] = music.name      # for attribution/credit
        video.save()
    _build_audio(narration, total, content_dur, music, audio_full)

    final = video.final_path
    _mux(visuals, audio_full, ass_path, final, source_ass=source_ass)
    log(f"final -> {final}")
    return final


def _source_ass(video) -> Path | None:
    info = video.manifest.get("article") or {}
    article = info.get("article", info) if isinstance(info, dict) else {}
    if not isinstance(article, dict):
        return None
    source = (article.get("site_name") or info.get("source_name") or "").strip()
    title = (article.get("title") or info.get("title") or "").strip()
    if not source:
        from urllib.parse import urlparse
        source = (urlparse(article.get("url") or info.get("url") or "").hostname or "").removeprefix("www.")
    if not source:
        return None
    from .source_card import render
    return render(source, title, video.dir / "source.ass", duration=1.8)


def _mux(visuals: Path, audio: Path, ass_path: Path | None, final: Path,
         source_ass: Path | None = None) -> None:
    filters = []
    current = "0:v"
    label_i = 0
    fonts = _ass_path_escape(config.FONT_DIR)
    for subtitle in (source_ass, ass_path):
        if subtitle and Path(subtitle).exists():
            next_label = f"v{label_i}"
            filters.append(f"[{current}]ass='{_ass_path_escape(Path(subtitle))}':fontsdir='{fonts}'[{next_label}]")
            current = next_label
            label_i += 1
    if filters:
        vf = ";".join(filters)
        run(["ffmpeg", "-y", "-i", str(visuals), "-i", str(audio),
             "-filter_complex", vf, "-map", f"[{current}]", "-map", "1:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    else:
        run(["ffmpeg", "-y", "-i", str(visuals), "-i", str(audio),
             "-map", "0:v", "-map", "1:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])


def build_preview_base(video) -> Path:
    """A voice-only (no music) render used by the dashboard's music preview, so a
    candidate track can be auditioned over it in the browser without re-encoding."""
    work = video.dir / "work"
    out = work / "preview_base.mp4"
    narration = work / "narration_full.wav"
    visuals = work / "visuals.mp4"
    if out.exists():
        return out
    if not (narration.exists() and visuals.exists()):
        raise FileNotFoundError("missing work artifacts; re-render this video first")
    content_dur = ffprobe_duration(narration)
    outro_dur = _outro_seconds()
    audio = work / "preview_audio.wav"
    _build_audio(narration, content_dur + outro_dur, content_dur, None, audio)  # voice only
    ass = video.dir / "captions.ass"
    _mux(visuals, audio, ass if ass.exists() else None, out, source_ass=_source_ass(video))
    return out


def remix_music(video, music_path: Path | None, volume: float = 0.16,
                start: float = 0.0) -> Path:
    """Re-fit a chosen music track over an already-produced video (dashboard music
    selector). Reuses the work/ artifacts; rebuilds audio and re-muxes the final."""
    work = video.dir / "work"
    narration = work / "narration_full.wav"
    visuals = work / "visuals.mp4"
    if not (narration.exists() and visuals.exists()):
        raise FileNotFoundError("missing work artifacts; re-render this video first")
    content_dur = ffprobe_duration(narration)
    outro_dur = _outro_seconds()
    total = content_dur + outro_dur
    audio = work / "audio_remix.wav"
    _build_audio(narration, total, content_dur, music_path, audio,
                 music_volume=volume, music_start=start)
    ass = video.dir / "captions.ass"
    _mux(visuals, audio, ass if ass.exists() else None, video.final_path,
         source_ass=_source_ass(video))
    if music_path:
        video.manifest["music"] = music_path.name
        video.manifest["music_volume"] = volume
        video.save()
    return video.final_path


def refresh_scene(video, script: Script, scene_index: int) -> Path:
    """Rebuild the FFmpeg timeline using cached audio and the other cached scene clips."""
    import json
    work = video.dir / "work"
    timeline_file = video.dir / "timeline.json"
    if not timeline_file.exists():
        raise FileNotFoundError("timeline is missing; render the video first")
    timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
    row = next((x for x in timeline["scenes"] if x["index"] == scene_index), None)
    scene = next((x for x in script.scenes if x.index == scene_index), None)
    if not row or not scene or scene.scene_type == "blank":
        raise ValueError("illustration scene not found")
    clip = work / f"clip_{scene_index:02d}.mp4"
    duration = float(row["end"]) - float(row["start"])
    preset = config.KEN_BURNS_CYCLE[(scene_index - 1) % len(config.KEN_BURNS_CYCLE)]
    illustrations = video.manifest.get("illustrations", {})
    saved_path = illustrations.get(str(scene_index)) if isinstance(illustrations, dict) else None
    image_path = Path(saved_path) if isinstance(saved_path, str) else video.scenes_dir / f"scene_{scene_index:02d}.png"
    if not image_path.exists():
        image_path = video.scenes_dir / f"scene_{scene_index:02d}.png"
    _ken_burns(image_path, duration, clip, preset)
    clips = [work / f"clip_{s.index:02d}.mp4" for s in script.scenes]
    if not all(p.exists() for p in clips):
        raise FileNotFoundError("cached scene renders are incomplete; render the video first")
    body = work / "body.mp4"
    _concat(clips, body, work, "scenes.txt")
    branded = body
    if config.ENABLE_WATERMARK:
        from .cards import render_watermark
        if not config.WATERMARK_PNG.exists():
            render_watermark()
        if config.WATERMARK_PNG.exists():
            branded = work / "body_branded.mp4"
            _overlay_watermark(body, config.WATERMARK_PNG, branded)
    visuals = work / "visuals.mp4"
    if config.ENABLE_OUTRO and config.PREBUILT_OUTRO.exists():
        outro = work / "existing_outro.mp4"
        content_dur = float(timeline["duration"])
        run(["ffmpeg", "-y", "-ss", f"{content_dur:.3f}", "-i", str(visuals), "-c", "copy", str(outro)])
        _concat([branded, outro], visuals, work, "final_concat.txt")
        outro.unlink(missing_ok=True)
    else:
        run(["ffmpeg", "-y", "-i", str(branded), "-c", "copy", str(visuals)])
    audio = work / "audio_full.wav"
    if not audio.exists():
        raise FileNotFoundError("cached audio is missing; render the video first")
    ass = video.dir / "captions.ass"
    _mux(visuals, audio, ass if ass.exists() else None, video.final_path,
         source_ass=_source_ass(video))
    return video.final_path
