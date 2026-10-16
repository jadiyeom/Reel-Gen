"""Environment diagnostic and healthcheck tool for ReelGen.

Checks dependencies, binaries, API keys, models, and assets, providing
actionable guidance for any missing or misconfigured components.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config


def check_environment() -> dict:
    """Run all health checks and return structured diagnostic results."""
    results = {
        "ok": True,
        "checks": [],
    }

    def add_check(name: str, status: str, message: str, fix: str = ""):
        if status == "fail":
            results["ok"] = False
        results["checks"].append({
            "name": name,
            "status": status,  # "pass", "warn", "fail"
            "message": message,
            "fix": fix,
        })

    # 1. Python version & venv
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        add_check("Python Version", "pass", f"Python {py_ver} (>= 3.10 required)")
    else:
        add_check("Python Version", "fail", f"Python {py_ver} is too old; Python 3.10+ required",
                  "Install Python 3.10 or newer.")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        add_check("Virtual Environment", "pass", f"Active venv at {sys.prefix}")
    else:
        add_check("Virtual Environment", "warn", "Running outside a virtual environment",
                  "Activate .venv with '.\\.venv\\Scripts\\activate' (Windows) or 'source .venv/bin/activate' (Linux/macOS).")

    # 2. FFmpeg & ffprobe
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            ver_out = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace")
            ver_line = ver_out.stdout.splitlines()[0] if ver_out.stdout else "unknown version"
            add_check("FFmpeg", "pass", f"{ver_line} ({ffmpeg_path})")
        except Exception as exc:
            add_check("FFmpeg", "warn", f"FFmpeg found at {ffmpeg_path} but error checking version: {exc}")
    else:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            add_check("FFmpeg", "pass", f"Using bundled imageio-ffmpeg at {exe}")
        except Exception:
            add_check("FFmpeg", "fail", "FFmpeg not found on PATH or via imageio-ffmpeg",
                      "Install FFmpeg from https://ffmpeg.org/download.html and add it to your PATH.")

    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        add_check("ffprobe", "pass", f"ffprobe found at {ffprobe_path}")
    else:
        add_check("ffprobe", "warn", "ffprobe not found on PATH (fallback duration reader will be used)",
                  "Install ffprobe alongside FFmpeg for fastest media probing.")

    # 3. Playwright & Chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        add_check("Playwright Chromium", "pass", "Chromium installed and operational")
    except Exception as exc:
        add_check("Playwright Chromium", "warn", f"Chromium not available ({exc})",
                  "Run 'python -m playwright install chromium' or 'python run.py setup'.")

    # 4. TTS Backends
    backend = config.TTS_BACKEND
    add_check("Configured TTS Backend", "pass", f"TTS_BACKEND={backend}")

    # Kokoro check
    try:
        import kokoro
        from kokoro import KPipeline
        from .kokoro_tts import VOICE_IDS
        voice = config.KOKORO_VOICE
        if voice in VOICE_IDS:
            add_check("Kokoro TTS", "pass", f"Kokoro installed; configured voice '{voice}' is valid")
        else:
            add_check("Kokoro TTS", "warn", f"Kokoro installed but voice '{voice}' not in verified voice pack list")
    except ImportError as exc:
        if backend == "kokoro":
            add_check("Kokoro TTS", "fail", f"kokoro package missing ({exc})",
                      "Run 'pip install \"kokoro>=0.9.4\"'.")
        else:
            add_check("Kokoro TTS", "warn", "kokoro package missing (fallback unavailable)",
                      "Run 'pip install \"kokoro>=0.9.4\"'.")

    # Chatterbox check
    if backend == "chatterbox":
        py_path = Path(os.getenv("CHATTERBOX_PYTHON", r"D:\AI\chatterbox-test\.venv\Scripts\python.exe")).expanduser()
        ref_path = Path(os.getenv("CHATTERBOX_REFERENCE_AUDIO", r"D:\AI\chatterbox-test\reference.mp3")).expanduser()
        if py_path.is_file():
            add_check("Chatterbox Python", "pass", f"Found at {py_path}")
        else:
            add_check("Chatterbox Python", "warn", f"Not found at {py_path}; Kokoro fallback will be used",
                      "Set CHATTERBOX_PYTHON in .env or switch to TTS_BACKEND=kokoro.")
        if ref_path.is_file():
            add_check("Chatterbox Reference", "pass", f"Found at {ref_path}")
        else:
            add_check("Chatterbox Reference", "warn", f"Not found at {ref_path}; Kokoro fallback will be used",
                      "Place reference audio at that path or set CHATTERBOX_REFERENCE_AUDIO in .env.")

    # 5. Whisper / Faster-Whisper
    try:
        import faster_whisper
        add_check("faster-whisper", "pass", f"faster-whisper version {getattr(faster_whisper, '__version__', 'ok')} installed")
        if config.WHISPER_DEVICE == "cuda":
            from .captions import _ensure_cuda_dlls
            _ensure_cuda_dlls()
            try:
                from faster_whisper import WhisperModel
                m = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16")
                add_check("Whisper CUDA", "pass", "NVIDIA CUDA acceleration active (float16)")
            except Exception as exc:  # noqa: BLE001
                add_check("Whisper CUDA", "warn", f"CUDA configured but unavailable ({exc}); fallback to CPU int8 active",
                          "Install CUDA 12 runtime DLLs or keep CPU fallback.")
    except ImportError as exc:
        add_check("faster-whisper", "fail", f"faster-whisper package missing: {exc}",
                  "Run 'pip install faster-whisper'.")

    # 6. APIs
    if config.OPENAI_API_KEY:
        add_check("OpenAI API Key", "pass", "Configured (OPENAI_API_KEY)")
    else:
        add_check("OpenAI API Key", "warn", "Not configured; offline sample scripts and timing will be used",
                  "Add OPENAI_API_KEY in .env to enable AI script writing and semantic clip matching.")

    if config.IMAGE_BACKEND == "fal":
        if config.FAL_KEY:
            add_check("fal.ai API Key", "pass", "Configured (FAL_KEY)")
        else:
            add_check("fal.ai API Key", "warn", "IMAGE_BACKEND=fal but FAL_KEY is empty",
                      "Add FAL_KEY in .env to generate Flux images / Wan motion.")

    if config.PEXELS_API_KEY:
        add_check("Pexels API Key", "pass", "Configured (PEXELS_API_KEY)")
    else:
        add_check("Pexels API Key", "warn", "Not configured (free stock fetching disabled)",
                  "Get a free API key at pexels.com/api and add PEXELS_API_KEY in .env.")

    # 7. Brand Assets & Outro
    if config.DEFAULT_OUTRO_IMAGE.is_file():
        add_check("Default Outro Artwork", "pass", f"Found at {config.DEFAULT_OUTRO_IMAGE.name}")
    else:
        add_check("Default Outro Artwork", "fail", f"Missing at {config.DEFAULT_OUTRO_IMAGE}",
                  "Restore assets/brand/backspace_outro.webp.")

    if config.LOGO_PNG.is_file():
        add_check("Brand Logo", "pass", f"Found at {config.LOGO_PNG.name}")
    else:
        add_check("Brand Logo", "warn", "No logo found at assets/logo/logo.png (watermark logo skipped)")

    # 8. Library status
    from . import library
    stats = library.stats()
    add_check("Clip Library", "pass", f"{stats['total']} clips in catalog ({stats['used']} used)")

    # 9. Social Publishing Connections
    yt = config.YOUTUBE_TOKEN_FILE.is_file()
    add_check("YouTube Connection", "pass" if yt else "warn",
              "Authorized" if yt else "Not connected (run 'python run.py connect-youtube')")

    ig = bool((config.INSTAGRAM_ACCESS_TOKEN or config.INSTAGRAM_TOKEN_FILE.is_file()) and config.INSTAGRAM_BUSINESS_ACCOUNT_ID)
    add_check("Instagram Connection", "pass" if ig else "warn",
              "Credentials present" if ig else "Not configured (set INSTAGRAM_ACCESS_TOKEN in .env)")

    fb = bool(config.FACEBOOK_PAGE_ID and (config.FACEBOOK_PAGE_ACCESS_TOKEN or config.FACEBOOK_PAGE_TOKEN_FILE.is_file()))
    add_check("Facebook Connection", "pass" if fb else "warn",
              "Page credentials present" if fb else "Not connected (run 'python run.py connect-facebook')")

    x_conn = bool(config.X_ACCESS_TOKEN or config.X_TOKEN_FILE.is_file())
    add_check("X Connection", "pass" if x_conn else "warn",
              "Authorized" if x_conn else "Not connected (run 'python run.py connect-x')")

    return results


def print_doctor_report() -> int:
    """Print an eye-catching formatted diagnostic report to terminal."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  [DOCTOR] ReelGen System Diagnostic & Environment Health")
    print("=" * 60 + "\n")

    res = check_environment()
    status_icons = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]"}

    passes = sum(1 for c in res["checks"] if c["status"] == "pass")
    warns = sum(1 for c in res["checks"] if c["status"] == "warn")
    fails = sum(1 for c in res["checks"] if c["status"] == "fail")

    for c in res["checks"]:
        tag = status_icons.get(c["status"], "[INFO]")
        print(f"  {tag:<6} {c['name']}: {c['message']}")
        if c["fix"] and c["status"] in ("fail", "warn"):
            print(f"         └─ Suggestion: {c['fix']}")

    print("\n" + "-" * 60)
    print(f"Summary: {passes} passed, {warns} warnings, {fails} failures.")
    if res["ok"]:
        print("System is in great shape! Ready to generate videos.")
        print("-" * 60 + "\n")
        return 0
    else:
        print("Some critical requirements are missing. Review the failures above.")
        print("-" * 60 + "\n")
        return 1
