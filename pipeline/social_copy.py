"""Small platform-native metadata builder for externally supplied scripts."""
from __future__ import annotations

import re

from .models import Script


def _hashtags(script: Script, limit: int) -> list[str]:
    out = []
    for tag in script.hashtags:
        value = re.sub(r"[^\w]", "", tag.strip().lstrip("#"), flags=re.UNICODE)
        if value and value.lower() not in {x.lower() for x in out}:
            out.append(value)
        if len(out) == limit:
            break
    return out


def _hook(script: Script) -> str:
    opening = next((s.narration.strip() for s in script.scenes if s.narration.strip()), script.topic)
    # Scene one may include both the hook and its grounding sentence. Keep only
    # the opening statement as the preview line and let the summary explain it.
    return re.split(r"(?<=[.!?])\s+", opening, maxsplit=1)[0]


def build(script: Script, article: dict | None = None) -> dict:
    """Build platform-native, discovery-friendly copy without unsupported claims."""
    article = article or {}
    title = (script.youtube_title or script.topic).strip()[:100]
    hook = _hook(script)
    summary = (script.youtube_description or script.topic).strip()
    source_name = str(article.get("site_name") or "").strip()
    source_url = str(article.get("url") or "").strip()
    # Put the searchable topic and actual premise near the start; keep the
    # description readable instead of stuffing it with repeated keywords.
    description = hook
    if summary and summary.casefold() != hook.casefold():
        description += f"\n\n{summary}"
    if source_name or source_url:
        description += "\n\nSource: " + (source_name or source_url)
        if source_url and source_url != source_name:
            description += f" — {source_url}"
    description += "\n\nWhat do you think? Share your take in the comments."

    caption = (script.instagram_caption or "").strip()
    if not caption:
        caption = hook
        if summary and summary.casefold() != hook.casefold():
            caption += f"\n\n{summary}"
    if not re.search(r"\b(comment|comments|share your take|tell us|save this)\b", caption, flags=re.I):
        caption += "\n\nWhat do you think? Share your take in the comments."
    if (source_name or source_url) and "\n\nSource:" not in caption:
        caption += f"\n\nSource: {source_name or source_url}"
    if source_url and source_url != source_name and source_url not in caption:
        caption += f" — {source_url}"

    # Prefer a few focused topic tags over broad or branded hashtag piles.
    tags = [tag for tag in _hashtags(script, 30)
            if tag.casefold() not in {source_name.casefold(), "reels", "viral", "fyp", "explorepage"}][:5]
    if tags:
        existing = {value.lower() for value in re.findall(r"(?<!\w)#([\w]+)", caption, flags=re.UNICODE)}
        missing = [tag for tag in tags if tag.lower() not in existing]
        if missing:
            caption += "\n\n" + " ".join(f"#{tag}" for tag in missing)
    x_text = (script.x_caption or hook).strip()
    if hook.casefold() not in x_text.casefold():
        x_text = hook + "\n\n" + x_text
    if source_url and source_url not in x_text:
        x_text += "\n\nSource: " + source_url
    if len(x_text) > 280:
        source_line = f"\n\n{source_url}" if source_url else ""
        budget = max(0, 277 - len(source_line))
        x_text = x_text[:budget].rstrip() + "…" + source_line
    return {
        "youtube": {"title": title, "description": description[:5000], "tags": _hashtags(script, 500)},
        "instagram": {"caption": caption[:2200]},
        "facebook": {"title": title, "description": description[:5000]},
        "x": {"text": x_text},
    }
