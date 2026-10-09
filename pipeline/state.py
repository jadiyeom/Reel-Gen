"""Per-video working folder (+ manifest) and a tiny sqlite tracking DB."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from . import config
from .util import read_json, write_json

DB_PATH = config.DATA / "state.db"


class Video:
    """Wraps one output folder: output/{date}-{slug}/ and its manifest.json.

    Each stage records its status + artifact paths so reruns skip finished work.
    """

    def __init__(self, slug: str, date: str | None = None):
        self.date = date or dt.date.today().isoformat()
        self.slug = slug
        self.dir = config.OUTPUT / f"{self.date}-{slug}"
        self.scenes_dir = self.dir / "scenes"
        self.audio_dir = self.dir / "audio"
        self.manifest_path = self.dir / "manifest.json"
        self.script_path = self.dir / "script.json"
        for d in (self.dir, self.scenes_dir, self.audio_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return read_json(self.manifest_path)
        return {"slug": self.slug, "date": self.date, "stages": {}, "scenes": []}

    def save(self) -> None:
        write_json(self.manifest_path, self.manifest)

    def stage_done(self, name: str) -> bool:
        return self.manifest["stages"].get(name, {}).get("done", False)

    def mark(self, name: str, **info) -> None:
        self.manifest["stages"][name] = {"done": True, **info}
        self.save()

    @property
    def final_path(self) -> Path:
        return self.dir / "final.mp4"


# --- tracking DB ------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                slug TEXT, date TEXT, topic TEXT, status TEXT,
                final_path TEXT, created_at TEXT,
                PRIMARY KEY (slug, date)
            );
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE, used INTEGER DEFAULT 0
            );
            """
        )


def record_video(v: Video, topic: str, status: str) -> None:
    init_db()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO videos VALUES (?,?,?,?,?,?)",
            (v.slug, v.date, topic, status, str(v.final_path),
             dt.datetime.now().isoformat(timespec="seconds")),
        )


def add_topics(topics: list[str]) -> int:
    init_db()
    n = 0
    with _conn() as c:
        for t in topics:
            try:
                c.execute("INSERT INTO topics (topic) VALUES (?)", (t.strip(),))
                n += 1
            except sqlite3.IntegrityError:
                pass
    return n


def next_topic() -> str | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT id, topic FROM topics WHERE used=0 ORDER BY id LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE topics SET used=1 WHERE id=?", (row["id"],))
            return row["topic"]
    return None


def list_videos() -> list[dict]:
    init_db()
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM videos ORDER BY date DESC, slug").fetchall()]
