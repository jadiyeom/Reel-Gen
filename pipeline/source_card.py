"""ASS source attribution, rendered independently of Whisper captions."""
from __future__ import annotations

from pathlib import Path

from . import config
from .captions import _cc, _hex_to_ass


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def render(source_name: str, article_title: str, out: Path, duration: float = 1.8) -> Path:
    """Write a subtle source card for the opening 1.8 seconds."""
    parchment_ink = _hex_to_ass(config.CAPTION_INK)
    terracotta = _hex_to_ass(config.CAPTION_TERRACOTTA)
    title = _escape(source_name)
    article_title = _escape(article_title)
    rows = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {config.WIDTH}",
        f"PlayResY: {config.HEIGHT}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: SourceLabel,{config.CAPTION_FONT},29,{terracotta},{terracotta},{parchment_ink},&HFF000000&,0,0,0,0,100,100,2,0,1,0,0,8,120,120,0,1",
        f"Style: SourceName,{config.CAPTION_FONT},54,{parchment_ink},{parchment_ink},{parchment_ink},&HFF000000&,1,0,0,0,100,100,0,0,1,0,0,8,120,120,0,1",
        f"Style: SourceTitle,{config.CAPTION_FONT},30,{parchment_ink},{parchment_ink},{parchment_ink},&HFF000000&,0,1,0,0,100,100,0,0,1,0,0,8,120,120,0,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    end = _cc(duration)
    fade = "{\\fad(160,260)}"
    rows.append(f"Dialogue: 2,0:00:00.00,{end},SourceLabel,,0,0,0,,{fade}{{\\an8\\pos({config.WIDTH//2},150)}}SOURCE")
    rows.append(f"Dialogue: 2,0:00:00.00,{end},SourceName,,0,0,0,,{fade}{{\\an8\\pos({config.WIDTH//2},198)}}{title}")
    if article_title:
        rows.append(f"Dialogue: 2,0:00:00.00,{end},SourceTitle,,0,0,0,,{fade}{{\\an8\\pos({config.WIDTH//2},260)}}{article_title}")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return out
