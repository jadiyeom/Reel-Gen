"""Central configuration: paths, brand constants, model + API settings.

Everything here is overridable via environment variables (a `.env` file is loaded
automatically). The pipeline is image-first: every scene is a generated cinematic
image with motion; the only on-screen text is the karaoke captions, and the voice
carries the message.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from threading import RLock
from pathlib import Path

from dotenv import load_dotenv

# --- Paths ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ASSETS = ROOT / "assets"
LOGO_DIR = ASSETS / "logo"
FONT_DIR = ASSETS / "fonts"
MUSIC_DIR = ASSETS / "music"
BRAND_DIR = ASSETS / "brand"
OUTRO_DIR = ASSETS / "outro"
TEMPLATES = ROOT / "templates"
PROMPTS = ROOT / "prompts"
OUTPUT = ROOT / "output"
DATA = ROOT / "data"

# --- Clip library -----------------------------------------------------------
LIBRARY = ROOT / "library"
LIB_IMAGES = LIBRARY / "images"
LIB_CLIPS = LIBRARY / "clips"
LIB_DB = LIBRARY / "index.db"
INVENTORY_CSV = LIBRARY / "inventory.csv"

for _d in (ASSETS, LOGO_DIR, FONT_DIR, MUSIC_DIR, BRAND_DIR, OUTRO_DIR, OUTPUT, DATA,
           LIBRARY, LIB_IMAGES, LIB_CLIPS):
    _d.mkdir(parents=True, exist_ok=True)


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Runtime matching: reuse a library clip when similarity >= threshold, else
# generate a new clip and add it to the library (match-then-generate).
EMBED_MODEL = "text-embedding-3-small"
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.40"))
RECENCY_WINDOW = int(os.getenv("RECENCY_WINDOW", "8"))   # don't reuse a clip used in the last N videos
USE_LIBRARY = _flag("USE_LIBRARY", True)

# Brand overlays (all optional). Drop your own square PNG at assets/logo/logo.png.
LOGO_PNG = LOGO_DIR / "logo.png"
WATERMARK_PNG = BRAND_DIR / "watermark.png"      # logo + disclaimer, composed once
OUTRO_CARD_PNG = BRAND_DIR / "outro_card.png"    # true-portrait end card
BRAND_PLATE = OUTRO_DIR / "brand_plate.png"      # optional landscape reference (unused)
PREBUILT_OUTRO = OUTRO_DIR / "outro.mp4"         # built once, stitched to every video
OUTRO_VO = OUTRO_DIR / "outro_vo.mp3"            # outro call-to-action voiceover

# Watermark is on by default (replace assets/logo/logo.png with yours, or set
# WATERMARK=false). The branded outro is opt-in (set OUTRO=true + your brand).
ENABLE_WATERMARK = _flag("WATERMARK", True)
ENABLE_OUTRO = _flag("OUTRO", False)
OUTRO_SECONDS = float(os.getenv("OUTRO_SECONDS", "3.6"))

# --- Video format -----------------------------------------------------------
WIDTH = 1080
HEIGHT = 1920
ASPECT_RATIO = "9:16"
FPS = 30
TARGET_SECONDS = int(os.getenv("TARGET_SECONDS", "30"))   # script target; prompt permits 20–45s as story needs
MIN_SCENE_SECONDS = 1.8
MAX_SCENE_SECONDS = 6.0
SCENE_PAD = 0.22                # silence after each line before the cut (snappy)

# --- Brand (override via env; used by watermark, outro, and the dashboard) ---
BRAND = {
    "name": os.getenv("BRAND_NAME", "Your Brand"),
    "url": os.getenv("BRAND_URL", ""),
    "tagline": os.getenv("BRAND_TAGLINE", ""),
    "disclaimer": os.getenv("BRAND_DISCLAIMER", ""),
    "bg": os.getenv("BRAND_BG", "#0B0F17"),
    "surface": os.getenv("BRAND_SURFACE", "#131A24"),
    "accent": os.getenv("BRAND_ACCENT", "#6366F1"),
    "accent_2": os.getenv("BRAND_ACCENT_2", "#8B5CF6"),
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "display_font": "Sora",
    "body_font": "Inter",
}
# Spoken call-to-action mixed under the outro (only used when OUTRO=true).
OUTRO_VO_TEXT = os.getenv("OUTRO_VO_TEXT", f"Follow {BRAND['name']}.")

# --- Content -----------------------------------------------------------------
# Optional niche/focus injected into the scriptwriter (e.g. "personal finance",
# "fitness motivation", "tech explainers"). Empty = purely topic-driven.
CONTENT_NICHE = os.getenv("CONTENT_NICHE", "").strip()
# Fallback topic when no topic is given and the backlog is empty.
DEFAULT_TOPIC = os.getenv("DEFAULT_TOPIC", "one small habit that quietly changes everything")
# Optional scriptwriter preset: a file in prompts/presets/ (name, with or without
# .md). Empty = the default prompts/scriptgen_system.md. See prompts/presets/README.md.
SCRIPT_PROMPT = os.getenv("SCRIPT_PROMPT", "").strip()

# --- Models / APIs ----------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GENERATION_MODE = os.getenv("GENERATION_MODE", "external").strip().lower()  # external | api
FAL_KEY = os.getenv("FAL_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")   # free at pexels.com/api
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "") # free at pixabay.com/api

# Length each library clip is trimmed to (stitch-time stretches to the scene).
LIB_CLIP_SECONDS = 5.0
# How many variants to fetch per stock query (you curate/delete the weak ones).
STOCK_VARIANTS = int(os.getenv("STOCK_VARIANTS", "5"))

SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "gpt-5-mini")   # sharpest scripts. Use "gpt-4o" for speed.
METADATA_MODEL = "gpt-4o-mini"

TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = os.getenv("TTS_VOICE", "onyx")
TTS_BACKEND = os.getenv("TTS_BACKEND", "kokoro").strip().lower()  # kokoro | openai | silent
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart").strip()
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
KOKORO_LANG = os.getenv("KOKORO_LANG", "en-us").strip().lower()
KOKORO_REPO_ID = os.getenv("KOKORO_REPO_ID", "hexgrad/Kokoro-82M").strip()
YOUTUBE_CLIENT_SECRETS = Path(os.getenv("YOUTUBE_CLIENT_SECRETS", str(DATA / "youtube_client_secrets.json")))
YOUTUBE_TOKEN_FILE = Path(os.getenv("YOUTUBE_TOKEN_FILE", str(DATA / "youtube_oauth_token.json")))
YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "private").strip().lower()
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
INSTAGRAM_GRAPH_VERSION = os.getenv("INSTAGRAM_GRAPH_VERSION", "v26.0").strip()
INSTAGRAM_VIDEO_URL_TEMPLATE = os.getenv("INSTAGRAM_VIDEO_URL_TEMPLATE", "")
# tunnel uses a temporary no-account Cloudflare Quick Tunnel; r2 stages the
# video in the optional S3-compatible bucket configured below.
INSTAGRAM_UPLOAD_MODE = os.getenv("INSTAGRAM_UPLOAD_MODE", "drive").strip().lower()
INSTAGRAM_DRIVE_TOKEN_FILE = Path(os.getenv("INSTAGRAM_DRIVE_TOKEN_FILE", str(DATA / "instagram_drive_oauth_token.json")))
# Optional S3-compatible public object storage (e.g. Cloudflare R2) lets the
# publisher stage a local video automatically for Instagram Login's video_url API.
INSTAGRAM_STORAGE_ENDPOINT_URL = os.getenv("INSTAGRAM_STORAGE_ENDPOINT_URL", "").strip()
INSTAGRAM_STORAGE_ACCESS_KEY_ID = os.getenv("INSTAGRAM_STORAGE_ACCESS_KEY_ID", "")
INSTAGRAM_STORAGE_SECRET_ACCESS_KEY = os.getenv("INSTAGRAM_STORAGE_SECRET_ACCESS_KEY", "")
INSTAGRAM_STORAGE_BUCKET = os.getenv("INSTAGRAM_STORAGE_BUCKET", "").strip()
INSTAGRAM_STORAGE_PUBLIC_BASE_URL = os.getenv("INSTAGRAM_STORAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")
INSTAGRAM_STORAGE_REGION = os.getenv("INSTAGRAM_STORAGE_REGION", "auto").strip()
INSTAGRAM_STORAGE_PREFIX = os.getenv("INSTAGRAM_STORAGE_PREFIX", "instagram-reels").strip("/")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "").strip()
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
FACEBOOK_GRAPH_VERSION = os.getenv("FACEBOOK_GRAPH_VERSION", INSTAGRAM_GRAPH_VERSION).strip()
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "").strip()
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_OAUTH_REDIRECT_URI = os.getenv(
    "FACEBOOK_OAUTH_REDIRECT_URI", "http://localhost:8765/facebook/callback"
).strip()
FACEBOOK_PAGE_TOKEN_FILE = Path(os.getenv(
    "FACEBOOK_PAGE_TOKEN_FILE", str(DATA / "facebook_page_token.json")
))
X_CLIENT_ID = os.getenv("X_CLIENT_ID", "").strip()
X_CLIENT_SECRET = os.getenv("X_CLIENT_SECRET", "")
X_OAUTH_REDIRECT_URI = os.getenv("X_OAUTH_REDIRECT_URI", "http://127.0.0.1:8766/x/callback").strip()
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_TOKEN_FILE = Path(os.getenv("X_TOKEN_FILE", str(DATA / "x_oauth_token.json")))
AUTO_PUBLISH_PLATFORMS = {p.strip().lower() for p in os.getenv("AUTO_PUBLISH_PLATFORMS", "").split(",") if p.strip()}
AUTO_PUBLISH_YOUTUBE_PRIVACY = os.getenv("AUTO_PUBLISH_YOUTUBE_PRIVACY", "private").strip().lower()
TTS_INSTRUCTIONS = os.getenv("TTS_INSTRUCTIONS", (
    "Fast, punchy, assertive viral short-form narrator. Speak QUICKLY with urgency "
    "and confidence — you are grabbing a scrolling viewer by the collar, loud and "
    "commanding but never shouting. Hit key words hard, minimal pauses, high energy "
    "from the very first word. Bold and intense, like a hype storyteller, not a lecture."
))
# Extra speed-up applied to the rendered voice (atempo). 1.0 = none.
SPEECH_TEMPO = float(os.getenv("SPEECH_TEMPO", "1.15"))

# --- Image generation -------------------------------------------------------
IMAGE_BACKEND = os.getenv("IMAGE_BACKEND", "fal")     # "fal" (Flux) | "local" (SDXL)
FAL_FLUX_MODEL = os.getenv("FAL_FLUX_MODEL", "fal-ai/flux/dev")
IMAGE_SIZE = {"width": 768, "height": 1344}           # 9:16, cover-cropped to 1080x1920
_IMAGE_SIZE_PORTRAIT = dict(IMAGE_SIZE)
IMAGE_STEPS = 28
# Consistent visual identity across every scene. Tune to taste (photoreal vs stylized).
IMAGE_STYLE = os.getenv("IMAGE_STYLE", (
    "cinematic still, dramatic moody lighting, shallow depth of field, volumetric haze, "
    "rich color grade with warm amber and deep teal accents, film grain, highly detailed, "
    "vertical 9:16 composition. No text, no letters, no numbers, no words, no captions, "
    "no signs, no labels, no logos, no watermark, no readable UI or screens."
))
_IMAGE_STYLE_BASE = IMAGE_STYLE
ILLUSTRATION_STYLE = os.getenv("ILLUSTRATION_STYLE", "visual_style.md")

# --- Motion (image -> video) ------------------------------------------------
# Every scene's still can be animated into a living clip via an i2v model.
#   ANIMATE = "all"  -> animate every scene (max quality, costs fal credit per clip)
#           = "none" -> Ken Burns zoom/pan only (free) — the cost-safe default
#           = "N"    -> animate the N most important scenes, Ken Burns the rest
ANIMATE = os.getenv("ANIMATE", "none")
# Sweet spot: Wan 2.2 5B at ~$0.15/clip. Swap to "fal-ai/wan-i2v" for 14B ($0.40).
I2V_MODEL = os.getenv("I2V_MODEL", "fal-ai/wan/v2.2-5b/image-to-video")
# Ken Burns presets cycle for varied motion on any non-animated scenes / fallback.
KEN_BURNS_CYCLE = ["in", "pan_right", "out", "pan_left", "in", "pan_up"]

# --- Captions ---------------------------------------------------------------
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
CAPTION_FONT = os.getenv("CAPTION_FONT", "Inter")
CAPTION_FONTSIZE = int(os.getenv("CAPTION_FONTSIZE", "78"))
_CAPTION_FONTSIZE_BASE = CAPTION_FONTSIZE
CAPTION_MARGIN_H = 140          # left+right margin so text wraps and never overflows
_CAPTION_MARGIN_H_BASE = CAPTION_MARGIN_H
CAPTION_MARGIN_V = int(os.getenv("CAPTION_MARGIN_V", "470"))
_CAPTION_MARGIN_V_BASE = CAPTION_MARGIN_V
CAPTION_POSITION = os.getenv("CAPTION_POSITION", "bottom").strip().lower()  # top | middle | bottom
CAPTION_COLOR = os.getenv("CAPTION_COLOR", "#C9573F")
CAPTION_PARCHMENT = os.getenv("CAPTION_PARCHMENT", "#F4E9D2")  # legacy paper color; used for source-card palettes
CAPTION_INK = os.getenv("CAPTION_INK", "#292723")
CAPTION_STROKE_COLOR = os.getenv("CAPTION_STROKE_COLOR", "#000000")
CAPTION_STROKE_WIDTH = float(os.getenv("CAPTION_STROKE_WIDTH", "2.0"))
CAPTION_SHADOW_OPACITY = float(os.getenv("CAPTION_SHADOW_OPACITY", "0.45"))
CAPTION_SHADOW_OFFSET = float(os.getenv("CAPTION_SHADOW_OFFSET", "3.0"))
CAPTION_SHADOW_BLUR = float(os.getenv("CAPTION_SHADOW_BLUR", "2.0"))
CAPTION_TERRACOTTA = os.getenv("CAPTION_TERRACOTTA", "#C9573F")
CAPTION_EMPHASIS_WORDS = {w.strip().lower() for w in os.getenv("CAPTION_EMPHASIS_WORDS", "").split(",") if w.strip()}
CAPTION_MAX_WORDS = int(os.getenv("CAPTION_MAX_WORDS", "4"))
CAPTION_MAX_CHARS = int(os.getenv("CAPTION_MAX_CHARS", "26"))
_VIDEO_FORMAT_LOCK = RLock()


@contextmanager
def video_format(aspect_ratio: str = "9:16"):
    """Temporarily set the render canvas and matching image/caption dimensions."""
    global WIDTH, HEIGHT, ASPECT_RATIO, IMAGE_SIZE, IMAGE_STYLE, PREBUILT_OUTRO, OUTRO_CARD_PNG, WATERMARK_PNG
    global CAPTION_FONTSIZE, CAPTION_MARGIN_H, CAPTION_MARGIN_V
    ratio = aspect_ratio.strip()
    if ratio not in {"9:16", "16:9"}:
        raise ValueError("aspect ratio must be 9:16 or 16:9")
    _VIDEO_FORMAT_LOCK.acquire()
    saved = (WIDTH, HEIGHT, ASPECT_RATIO, dict(IMAGE_SIZE), IMAGE_STYLE,
             CAPTION_FONTSIZE, CAPTION_MARGIN_H, CAPTION_MARGIN_V,
             PREBUILT_OUTRO, OUTRO_CARD_PNG, WATERMARK_PNG)
    if ratio == "16:9":
        WIDTH, HEIGHT = 1920, 1080
        ASPECT_RATIO = ratio
        PREBUILT_OUTRO = OUTRO_DIR / "outro-1920x1080.mp4"
        OUTRO_CARD_PNG = BRAND_DIR / "outro_card-1920x1080.png"
        WATERMARK_PNG = BRAND_DIR / "watermark-1920x1080.png"
        IMAGE_SIZE = {"width": 1344, "height": 768}
        IMAGE_STYLE = (_IMAGE_STYLE_BASE.replace("vertical 9:16 composition", "horizontal 16:9 composition")
                       .replace("vertical 9:16", "horizontal 16:9"))
        CAPTION_FONTSIZE = 64 if CAPTION_FONTSIZE == _CAPTION_FONTSIZE_BASE else CAPTION_FONTSIZE
        CAPTION_MARGIN_H = 150 if CAPTION_MARGIN_H == _CAPTION_MARGIN_H_BASE else CAPTION_MARGIN_H
        CAPTION_MARGIN_V = 150
    else:
        WIDTH, HEIGHT, ASPECT_RATIO = 1080, 1920, ratio
        PREBUILT_OUTRO = OUTRO_DIR / "outro.mp4"
        OUTRO_CARD_PNG = BRAND_DIR / "outro_card.png"
        WATERMARK_PNG = BRAND_DIR / "watermark.png"
        IMAGE_SIZE = dict(_IMAGE_SIZE_PORTRAIT)
        IMAGE_STYLE = _IMAGE_STYLE_BASE
        CAPTION_FONTSIZE = _CAPTION_FONTSIZE_BASE
        CAPTION_MARGIN_H = _CAPTION_MARGIN_H_BASE
        CAPTION_MARGIN_V = _CAPTION_MARGIN_V_BASE
    _sync_render_modules()
    try:
        yield
    finally:
        (WIDTH, HEIGHT, ASPECT_RATIO, IMAGE_SIZE, IMAGE_STYLE, CAPTION_FONTSIZE,
         CAPTION_MARGIN_H, CAPTION_MARGIN_V, PREBUILT_OUTRO, OUTRO_CARD_PNG, WATERMARK_PNG) = saved
        _sync_render_modules()
        _VIDEO_FORMAT_LOCK.release()


def _sync_render_modules() -> None:
    """Keep the assembler's legacy module-level canvas in sync with config."""
    import sys
    assemble = sys.modules.get("pipeline.assemble")
    if assemble is not None:
        assemble.W, assemble.H, assemble.FPS = WIDTH, HEIGHT, FPS
    outro = sys.modules.get("pipeline.outro")
    if outro is not None:
        outro.W, outro.H, outro.FPS = WIDTH, HEIGHT, FPS


def composition_instruction() -> str:
    return ("Compose for a horizontal 16:9 landscape frame; distribute important elements across the wide frame."
            if ASPECT_RATIO == "16:9" else
            "Compose for a vertical 9:16 portrait frame; keep the principal subject legible at phone size.")

# --- Watermark --------------------------------------------------------------
WATERMARK_LOGO_PX = int(os.getenv("WATERMARK_LOGO_PX", "96"))   # bottom-right logo size
WATERMARK_OPACITY = float(os.getenv("WATERMARK_OPACITY", "0.9"))

# Local SDXL (free fallback). Few-step model fits a 6 GB GPU.
SDXL_MODEL = os.getenv("SDXL_MODEL", "stabilityai/sdxl-turbo")

# Narration pacing fallback when no API key is set (offline smoke tests).
WORDS_PER_MINUTE = 165
