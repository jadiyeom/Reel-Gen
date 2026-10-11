"""Bridge to a persistent Chatterbox Turbo process in its isolated virtual environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from .util import ffprobe_duration


class ChatterboxWorker:
    """Keep the model loaded once for all scenes in a single render."""

    def __init__(self) -> None:
        default_python = Path(r"D:\AI\chatterbox-test\.venv\Scripts\python.exe")
        default_reference = Path(r"D:\AI\chatterbox-test\reference.mp3")
        self.python = Path(os.getenv("CHATTERBOX_PYTHON", str(default_python))).expanduser()
        self.reference = Path(os.getenv("CHATTERBOX_REFERENCE_AUDIO", str(default_reference))).expanduser()
        self.worker_script = Path(__file__).with_name("chatterbox_worker.py")
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if not self.python.is_file():
            raise RuntimeError(
                f"Chatterbox Python not found: {self.python}. Set CHATTERBOX_PYTHON in .env."
            )
        if not self.reference.is_file():
            raise RuntimeError(
                f"Chatterbox reference audio not found: {self.reference}. "
                "Set CHATTERBOX_REFERENCE_AUDIO in .env."
            )
        self.process = subprocess.Popen(
            [str(self.python), "-u", str(self.worker_script), str(self.reference)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            text=True, encoding="utf-8", bufsize=1,
        )
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        try:
            status = json.loads(line)
        except json.JSONDecodeError as exc:
            self.close()
            raise RuntimeError(f"Chatterbox worker returned unexpected startup output: {line!r}") from exc
        if not status.get("ready"):
            self.close()
            raise RuntimeError(status.get("error", "Chatterbox worker failed to start"))
        from .util import log
        log(f"Chatterbox Turbo ready on {status.get('device', 'unknown device')} using {self.reference}")

    def generate(self, text: str, output_path: Path) -> float:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Chatterbox worker is not running")
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps({"text": text, "output": str(output_path)}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        try:
            result = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Chatterbox worker returned unexpected output: {line!r}") from exc
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Chatterbox generation failed"))
        duration = ffprobe_duration(output_path)
        if duration <= 0:
            raise RuntimeError(f"Chatterbox wrote an unreadable audio file: {output_path}")
        return duration

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(json.dumps({"command": "stop"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=10)
        except Exception:
            process.kill()
            process.wait()
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def __enter__(self) -> "ChatterboxWorker":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
