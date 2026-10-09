"""AI short-form video pipeline — CLI (clip library + match-then-generate).

Usage:
  python run.py setup                 one-time: install Chromium, build overlays
  python run.py fetch-library [N]     fill the library with FREE Pexels/Pixabay footage (N = limit)
  python run.py gen-library [N]       AI-generate library clips from inventory.csv (fal)
  python run.py library-stats         show library counts / usage
  python run.py make ["topic"]        generate one short (reuses library, generates on miss)
  python run.py make-url URL           generate an illustrated short from an article URL
  python run.py make-url URL --aspect-ratio 16:9  render for standard YouTube landscape
  python run.py init-external [NAME]   create script.json + images/ input folder for ChatGPT-made assets
  python run.py render-external --article-url URL --script PATH [--images-dir PATH] [--aspect-ratio 16:9] [--no-captions]
                                      render supplied script/storyboard and illustrations locally
  python run.py connect-youtube        connect a YouTube channel with Google OAuth
  python run.py connect-instagram-drive authorize temporary Instagram upload staging in Google Drive
  python run.py connect-facebook       connect/reconnect a Facebook Page for Reel publishing
  python run.py connect-x              connect/reconnect an X account for video posts
  python run.py publish VIDEO [--platform youtube|instagram|facebook|x|both|all] [--dry-run|--confirm]
                                      preview platform copy or publish a finished reel
  python run.py batch N               generate N shorts from the backlog
  python run.py topics import|add ... manage the topic backlog
  python run.py build-outro [--force] (re)build the optional branded outro clip
  python run.py build-watermark       (re)build the watermark overlay
  python run.py list                  list generated videos
  python run.py serve                 launch the review/workflow dashboard
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from pipeline import cards, config, library, state
from pipeline.produce import make
from pipeline.util import log, step


def batch(n: int) -> None:
    for i in range(n):
        step(f"=== video {i+1}/{n} ===")
        final = make(None)
        print(f"[DONE] {final}")


def setup() -> None:
    step("Setup")
    import subprocess
    log("installing Playwright Chromium ...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    if config.LOGO_PNG.exists():
        cards.render_watermark()
    else:
        log(f"no logo at {config.LOGO_PNG} — drop a square PNG there for a watermark "
            "(or set WATERMARK=false / a BRAND_DISCLAIMER in .env).")
    if config.ENABLE_OUTRO:
        from pipeline.outro import build_outro
        build_outro(force=True)
    log("setup done.")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "make"
    if cmd == "setup":
        setup()
    elif cmd == "fetch-library":
        from pipeline.stock import fetch_library
        fetch_library(limit=int(args[1]) if len(args) > 1 else None)
    elif cmd == "gen-library":
        from pipeline.generate_library import generate
        generate(limit=int(args[1]) if len(args) > 1 else None)
    elif cmd == "library-stats":
        print(library.stats())
    elif cmd == "make":
        import argparse
        parser = argparse.ArgumentParser(prog="run.py make")
        parser.add_argument("topic", nargs="?")
        parser.add_argument("--aspect-ratio", choices=("9:16", "16:9"), default="9:16")
        opts = parser.parse_args(args[1:])
        with config.video_format(opts.aspect_ratio):
            final = make(opts.topic)
        print(f"\n[DONE] {final}")
    elif cmd == "make-url" and len(args) > 1:
        import argparse
        parser = argparse.ArgumentParser(prog="run.py make-url")
        parser.add_argument("url")
        parser.add_argument("--aspect-ratio", choices=("9:16", "16:9"), default="9:16")
        opts = parser.parse_args(args[1:])
        if config.GENERATION_MODE != "api":
            raise SystemExit("make-url uses OpenAI generation. For supplied assets, use render-external --article-url URL --script STORYBOARD.json")
        with config.video_format(opts.aspect_ratio):
            final = make(None, article_url=opts.url)
        print(f"\n[DONE] {final}")
    elif cmd == "init-external":
        import argparse
        from pipeline.external import create_external_workspace
        parser = argparse.ArgumentParser(prog="run.py init-external")
        parser.add_argument("name", nargs="?", default="", help="folder/topic name (optional)")
        opts = parser.parse_args(args[1:])
        folder = create_external_workspace(opts.name)
        print(f"[DONE] Created {folder}")
        print(f"Edit storyboard: {folder / 'script.json'}")
        print(f"Save illustrations in: {folder / 'images'}")
        print("Render with: python run.py render-external --article-url URL "
              f"--script \"{folder / 'script.json'}\" --images-dir \"{folder / 'images'}\"")
    elif cmd == "render-external":
        import argparse
        from pathlib import Path
        parser = argparse.ArgumentParser(prog="run.py render-external")
        parser.add_argument("--article-url", required=True)
        parser.add_argument("--script", required=True)
        parser.add_argument("--images-dir")
        parser.add_argument("--aspect-ratio", choices=("9:16", "16:9"), default="9:16",
                            help="output canvas (default: 9:16)")
        parser.add_argument("--no-captions", action="store_false", dest="render_captions",
                            default=True, help="render audio and visuals without burned-in captions")
        opts = parser.parse_args(args[1:])
        from pipeline.external import render_external
        with config.video_format(opts.aspect_ratio):
            final = render_external(opts.article_url, Path(opts.script),
                                    Path(opts.images_dir) if opts.images_dir else None,
                                    render_captions=opts.render_captions)
        print(f"\n[DONE] {final}")
    elif cmd == "connect-youtube":
        from pipeline.publish import connect_youtube
        print(f"YouTube connected. OAuth token saved at {connect_youtube()}")
    elif cmd == "connect-instagram-drive":
        from pipeline.publish import connect_instagram_drive
        print(f"Google Drive connected. OAuth token saved at {connect_instagram_drive()}")
    elif cmd == "connect-facebook":
        from pipeline.publish import connect_facebook_page
        page = connect_facebook_page()
        print(f"Facebook Page connected: {page['name']} ({page['id']}). Token saved locally at {page['token_file']}.")
    elif cmd == "connect-x":
        from pipeline.publish import connect_x
        print(f"X connected. OAuth credentials saved locally at {connect_x()}.")
    elif cmd == "publish":
        import argparse
        import json
        from pathlib import Path
        from pipeline.models import Script
        from pipeline.publish import publish
        from pipeline.social_copy import build as build_social_copy
        from pipeline.util import read_json
        parser = argparse.ArgumentParser(prog="run.py publish")
        parser.add_argument("video", help="finished MP4 or its output directory")
        parser.add_argument("--platform", choices=("youtube", "instagram", "facebook", "x", "both", "all"), default="both")
        parser.add_argument("--privacy-status", choices=("private", "unlisted", "public"), default=config.YOUTUBE_PRIVACY_STATUS)
        parser.add_argument("--instagram-video-url", default="", help="publicly reachable URL for the Instagram API to fetch")
        parser.add_argument("--dry-run", action="store_true", help="show platform copy without connecting or publishing")
        parser.add_argument("--confirm", action="store_true", help="confirm external upload/publication")
        opts = parser.parse_args(args[1:])
        video = Path(opts.video).resolve()
        if video.is_dir():
            video = video / "final.mp4"
        if opts.dry_run:
            manifest_path = video.parent / "manifest.json"
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
            script = Script.model_validate(read_json(video.parent / "script.json"), context={
                "allow_extended_storyboard": bool(manifest.get("extended_storyboard"))})
            article_file = video.parent / "article.json"
            article = read_json(article_file) if article_file.exists() else {}
            print(json.dumps(build_social_copy(script, article), ensure_ascii=False, indent=2))
        else:
            if opts.platform == "both":
                platforms = ("youtube", "instagram")
            elif opts.platform == "all":
                platforms = ("youtube", "instagram", "facebook", "x")
            else:
                platforms = (opts.platform,)
            result = publish(video, platforms=platforms, privacy_status=opts.privacy_status,
                             instagram_video_url=opts.instagram_video_url, confirm=opts.confirm)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "batch":
        batch(int(args[1]) if len(args) > 1 else 1)
    elif cmd == "build-outro":
        from pipeline.outro import build_outro
        build_outro(force="--force" in args)
    elif cmd == "build-watermark":
        cards.render_watermark()
    elif cmd == "topics" and len(args) > 1 and args[1] == "add":
        print(f"added {state.add_topics(args[2:])} topics")
    elif cmd == "topics" and len(args) > 1 and args[1] == "import":
        f = config.DATA / "topics.txt"
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        print(f"imported {state.add_topics(lines)} topics from {f.name}")
    elif cmd == "list":
        for v in state.list_videos():
            print(f"{v['date']}  {v['status']:10}  {v['slug']}")
    elif cmd == "serve":
        from dashboard.app import run_server
        run_server()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
