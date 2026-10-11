"""Persistent Chatterbox Turbo worker, run with the dedicated Chatterbox Python.""" 
from __future__ import annotations

import contextlib
import json
import sys
import traceback
from pathlib import Path

import torch
import torchaudio
from chatterbox.tts_turbo import ChatterboxTurboTTS


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) != 2:
        emit({"ok": False, "error": "Expected reference-audio path argument"})
        return 2
    reference = Path(sys.argv[1])
    if not reference.is_file():
        emit({"ok": False, "error": f"Reference audio not found: {reference}"})
        return 2
    try:
        with contextlib.redirect_stdout(sys.stderr):
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = ChatterboxTurboTTS.from_pretrained(device=device)
        emit({"ready": True, "device": device})
    except Exception as exc:
        emit({"ok": False, "error": f"Could not load Chatterbox Turbo: {exc}"})
        return 1

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "stop":
                emit({"ok": True, "stopped": True})
                return 0
            text = str(request.get("text", "")).strip()
            output = Path(request["output"])
            if not text:
                emit({"ok": False, "error": "Narration text is empty"})
                continue
            with contextlib.redirect_stdout(sys.stderr):
                audio = model.generate(text, audio_prompt_path=str(reference))
                output.parent.mkdir(parents=True, exist_ok=True)
                torchaudio.save(str(output), audio.detach().cpu(), model.sr)
            emit({"ok": True, "output": str(output)})
        except Exception as exc:
            emit({"ok": False, "error": f"{exc}", "traceback": traceback.format_exc()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
