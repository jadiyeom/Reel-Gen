"""Clip library catalog: stores every generated image+animation with tags and a
text embedding, and matches script scenes to the best existing clip at runtime.

This is what lets us stop re-generating similar scenes: generate once, reuse forever.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path

from . import config
from .util import log


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.LIB_DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                grp TEXT, lighting TEXT, style TEXT,
                description TEXT, image_prompt TEXT, motion_prompt TEXT,
                image_path TEXT, video_path TEXT,
                embedding TEXT, duration REAL,
                times_used INTEGER DEFAULT 0, last_used_at TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS clip_usage (
                clip_id TEXT, video_slug TEXT, ts TEXT
            );
            """
        )


def has(clip_id: str) -> bool:
    init_db()
    with _conn() as c:
        return c.execute("SELECT 1 FROM clips WHERE id=?", (clip_id,)).fetchone() is not None


def embed(text: str) -> list[float]:
    """Embed text with OpenAI; returns [] if no API key (matching then disabled)."""
    if not config.OPENAI_API_KEY:
        return []
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    r = client.embeddings.create(model=config.EMBED_MODEL, input=text[:2000])
    return r.data[0].embedding


def add_clip(row: dict, image_path: Path, video_path: Path, duration: float,
             embedding: list[float]) -> None:
    init_db()
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO clips
               (id, grp, lighting, style, description, image_prompt, motion_prompt,
                image_path, video_path, embedding, duration, times_used, last_used_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,
                       COALESCE((SELECT times_used FROM clips WHERE id=?),0), NULL, ?)""",
            (row["id"], row["group"], row["lighting"], row["style"], row["description"],
             row["image_prompt"], row["motion_prompt"], str(image_path), str(video_path),
             json.dumps(embedding), duration, row["id"],
             dt.datetime.now().isoformat(timespec="seconds")),
        )


def all_clips() -> list[dict]:
    init_db()
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM clips ORDER BY id").fetchall()]


def count() -> int:
    init_db()
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM clips").fetchone()[0]


def _recent_clip_ids(n: int) -> set[str]:
    with _conn() as c:
        slugs = [r[0] for r in c.execute(
            "SELECT DISTINCT video_slug FROM clip_usage ORDER BY ts DESC LIMIT ?", (n,)).fetchall()]
        if not slugs:
            return set()
        q = "SELECT DISTINCT clip_id FROM clip_usage WHERE video_slug IN (%s)" % ",".join("?" * len(slugs))
        return {r[0] for r in c.execute(q, slugs).fetchall()}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search_top(query_text: str, exclude_ids: set[str] | None = None,
               k: int = 12, apply_recency: bool = True) -> list[tuple[dict, float]]:
    """Return up to k (clip, score) pairs ranked by similarity to the query."""
    init_db()
    qvec = embed(query_text)
    if not qvec:
        return []
    exclude = set(exclude_ids or set())
    if apply_recency:
        exclude |= _recent_clip_ids(config.RECENCY_WINDOW)
    scored = []
    for clip in all_clips():
        if clip["id"] in exclude:
            continue
        try:
            vec = json.loads(clip["embedding"]) if clip["embedding"] else []
        except (json.JSONDecodeError, TypeError):
            vec = []
        score = _cosine(qvec, vec) - clip["times_used"] * 0.001
        scored.append((clip, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


def search(query_text: str, exclude_ids: set[str] | None = None) -> tuple[dict | None, float]:
    """Best single match (recency-aware) — used by the auto matcher."""
    top = search_top(query_text, exclude_ids, k=1, apply_recency=True)
    return top[0] if top else (None, 0.0)


def get_clip(clip_id: str) -> dict | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        return dict(row) if row else None


def update_description(clip_id: str, description: str) -> bool:
    """Edit a clip's description and re-embed it so matching reflects the change."""
    init_db()
    clip = get_clip(clip_id)
    if not clip:
        return False
    emb = embed(f"{description} ({clip['grp']})")
    with _conn() as c:
        c.execute("UPDATE clips SET description=?, embedding=? WHERE id=?",
                  (description, json.dumps(emb), clip_id))
    return True


def mark_used(clip_id: str, video_slug: str) -> None:
    init_db()
    with _conn() as c:
        c.execute("UPDATE clips SET times_used=times_used+1, last_used_at=? WHERE id=?",
                  (dt.datetime.now().isoformat(timespec="seconds"), clip_id))
        c.execute("INSERT INTO clip_usage VALUES (?,?,?)",
                  (clip_id, video_slug, dt.datetime.now().isoformat(timespec="seconds")))


def delete_clip(clip_id: str) -> bool:
    """Remove a clip from the catalog and delete its files (curation)."""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT image_path, video_path FROM clips WHERE id=?", (clip_id,)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM clips WHERE id=?", (clip_id,))
        c.execute("DELETE FROM clip_usage WHERE clip_id=?", (clip_id,))
    for p in (row["image_path"], row["video_path"]):
        try:
            from pathlib import Path
            Path(p).unlink(missing_ok=True)
        except (OSError, TypeError):
            pass
    return True


def stats() -> dict:
    init_db()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        used = c.execute("SELECT COUNT(*) FROM clips WHERE times_used>0").fetchone()[0]
        by_group = {r[0]: r[1] for r in c.execute(
            "SELECT grp, COUNT(*) FROM clips GROUP BY grp").fetchall()}
    return {"total": total, "used": used, "by_group": by_group}
