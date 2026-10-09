"""Brand overlays for the image-first pipeline.

- render_watermark: transparent PNG with an optional logo (bottom-right) + an
  optional disclaimer (bottom). Composed once, overlaid on the moving content so it
  never zooms with the footage. Returns None if there's nothing to show.
- render_outro_card: the opt-in end card (logo + brand name + tagline + CTA).
- render_fallback_bg: a clean, text-free cinematic gradient used only if image
  generation fails for a scene (captions still carry the words).
"""
from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .util import log

_env = Environment(
    loader=FileSystemLoader(str(config.TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def _logo_data_uri() -> str:
    if config.LOGO_PNG.exists():
        enc = base64.b64encode(config.LOGO_PNG.read_bytes()).decode()
        return f"data:image/png;base64,{enc}"
    return ""


def render_watermark(out: Path = None) -> Path | None:
    """Render the transparent logo+disclaimer overlay (cached at WATERMARK_PNG).

    Returns None (and renders nothing) when there is neither a logo nor a
    disclaimer to show, so the assembler can skip the overlay entirely.
    """
    out = out or config.WATERMARK_PNG
    b = config.BRAND
    logo_data = _logo_data_uri()
    if not logo_data and not b["disclaimer"]:
        return None

    from playwright.sync_api import sync_playwright

    html = _env.get_template("watermark.html").render(
        w=config.WIDTH, h=config.HEIGHT, body_font=b["body_font"],
        disclaimer=b["disclaimer"], logo_data=logo_data,
        logo_px=config.WATERMARK_LOGO_PX, opacity=config.WATERMARK_OPACITY,
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": config.WIDTH, "height": config.HEIGHT},
                                device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(120)
        page.screenshot(path=str(out), type="png", omit_background=True)
        browser.close()
    log(f"watermark -> {out.name}")
    return out


def render_outro_card(out: Path = None) -> Path:
    """Render the true-portrait end card (logo + brand name + tagline + CTA)."""
    from playwright.sync_api import sync_playwright

    out = out or config.OUTRO_CARD_PNG
    b = config.BRAND
    html = _env.get_template("outro_card.html").render(
        w=config.WIDTH, h=config.HEIGHT, display_font=b["display_font"],
        body_font=b["body_font"], accent=b["accent"], accent_2=b["accent_2"],
        text=b["text"], muted=b["muted"], name=b["name"], url=b["url"],
        tagline=b["tagline"], logo_data=_logo_data_uri(),
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": config.WIDTH, "height": config.HEIGHT},
                                device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(150)
        page.screenshot(path=str(out), type="png")
        browser.close()
    log(f"outro card -> {out.name}")
    return out


def render_fallback_bg(out: Path) -> Path:
    """Text-free cinematic gradient, used only when image generation fails."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = config.WIDTH, config.HEIGHT
    img = Image.new("RGB", (w, h), config.BRAND["bg"])
    glow = Image.new("RGB", (w, h), config.BRAND["bg"])
    d = ImageDraw.Draw(glow)
    d.ellipse([w * 0.1, h * 0.1, w * 0.9, h * 0.6], fill=(60, 40, 10))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    Image.blend(img, glow, 0.6).save(out)
    return out
