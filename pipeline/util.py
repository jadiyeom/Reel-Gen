"""Small shared helpers: ffmpeg/ffprobe wrappers, slugify, logging."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import shutil
from pathlib import Path


def log(msg: str) -> None:
    print(f"   - {msg}", flush=True)


def step(msg: str) -> None:
    print(f"\n>> {msg}", flush=True)


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60].strip("-") or "short"


def run(cmd: list[str], quiet: bool = True) -> None:
    """Run a subprocess, raising with captured output on failure."""
    if cmd and cmd[0] == "ffmpeg" and not shutil.which("ffmpeg"):
        try:
            import imageio_ffmpeg
            cmd = [imageio_ffmpeg.get_ffmpeg_exe(), *cmd[1:]]
        except ImportError as e:
            raise RuntimeError("FFmpeg is required; install it or add imageio-ffmpeg") from e
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        sys.stdout.write(proc.stdout)
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd[:3])} ...")
    if not quiet:
        sys.stdout.write(proc.stdout)


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds."""
    if shutil.which("ffprobe"):
        out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True,
        )
        try:
            return float(out.stdout.strip())
        except (ValueError, AttributeError):
            pass
    # imageio-ffmpeg bundles ffmpeg but not ffprobe. Its diagnostic includes a
    # reliable container duration for our generated media files.
    try:
        import imageio_ffmpeg
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)],
                             capture_output=True, text=True)
        match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr or "")
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except (ImportError, OSError):
        pass
    return 0.0


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
