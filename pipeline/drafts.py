"""Persisted drafts for the Create workflow.

A draft captures everything in-progress (topic, options, script, chosen clips,
stage) so closing the tab never loses work — you resume right where you left off.
Stored as JSON under data/drafts/.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid

from . import config

DRAFTS_DIR = config.DATA / "drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def save(draft: dict) -> str:
    if not draft.get("id"):
        draft["id"] = uuid.uuid4().hex[:8]
        draft["created"] = _now()
    draft["updated"] = _now()
    (DRAFTS_DIR / f"{draft['id']}.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft["id"]


def load(draft_id: str) -> dict | None:
    f = DRAFTS_DIR / f"{draft_id}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def delete(draft_id: str) -> bool:
    f = DRAFTS_DIR / f"{draft_id}.json"
    if f.exists():
        f.unlink()
        return True
    return False


def list_drafts() -> list[dict]:
    items = []
    for f in DRAFTS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        s = d.get("script") or {}
        items.append({"id": d.get("id"), "stage": d.get("stage", "draft"),
                      "topic": d.get("topic") or s.get("topic") or "(untitled)",
                      "title": s.get("youtube_title", ""), "vid": d.get("vid"),
                      "updated": d.get("updated", "")})
    items.sort(key=lambda x: x["updated"], reverse=True)
    return items
