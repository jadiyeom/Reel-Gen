"""Match a script scene to the best existing library clip (or signal a miss)."""
from __future__ import annotations

from . import config, library
from .models import Scene


def match_scene(scene: Scene, used_ids: set[str]) -> tuple[dict | None, float]:
    """Return (clip, score) if a library clip matches well enough, else (None, score)."""
    if not (config.USE_LIBRARY and library.count() > 0):
        return None, 0.0
    clip, score = library.search(scene.image_prompt, exclude_ids=used_ids)
    if clip and score >= config.MATCH_THRESHOLD:
        return clip, score
    return None, score


def candidates(query: str, used_ids: set[str], k: int = 12) -> list[dict]:
    """Top clip options for a scene (for the preview/swap UI), best first."""
    out = []
    for clip, score in library.search_top(query, exclude_ids=used_ids, k=k, apply_recency=False):
        out.append({"id": clip["id"], "description": clip["description"],
                    "group": clip["grp"], "score": round(score, 3)})
    return out
