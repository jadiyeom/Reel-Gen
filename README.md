# ReelGen — AI Short-Form Video Production

> Turn an idea or article into a short-form video workflow: script, visual direction, voiceover, captions, music, and export-ready MP4s for **YouTube Shorts, TikTok, and Instagram Reels**.

**ReelGen** is an AI-assisted short-form video production workspace. Its local Python app can write scripts, generate or reuse visuals, create narration, burn in timed captions, mix music, and export a `1080×1920` MP4 with platform-specific copy. The repository also includes a lightweight hosted storyboard builder at `index.html` for planning and exporting a `storyboard.json`.

It works **two ways**, and you can mix them per video:

- 🎨 **Generate with AI** — cinematic images via **Flux** and motion clips via **Wan** on [fal.ai](https://fal.ai).
- 🎞️ **Pull from a clip library** — free real stock footage from **Pexels / Pixabay**, plus a reusable semantic library so you generate a shot once and reuse it forever (**match-then-generate**).

> 🛠️ *A weekend project, shared openly in case it's useful to you too. Fork it, break it, build on it.*

<p align="center">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg">
  <img alt="PRs Welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg">
</p>

---

## Deploy the hosted storyboard builder

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fjadiyeom%2FReel-Gen&project-name=reelgen)

Import this repository into Vercel and deploy the root directory. The hosted page is a static, browser-based storyboard planner; **it does not run AI generation, render MP4s, or publish to social platforms on Vercel**. It requires no environment variables and does not send your storyboard to a server. Export the JSON and use it with your local ReelGen renderer.

The full Python pipeline remains available locally. A truly hosted render service needs durable object storage and a persistent job worker/queue, and should be added as a separate deployment layer rather than relying on ephemeral serverless disk.

## ✨ Features

- **Topic → finished video**, end to end, in one command.
- **Two visual modes:** AI generation (fal Flux + Wan) and/or free stock footage (Pexels/Pixabay).
- **Reusable clip library** with semantic matching — reuse a good shot across videos instead of paying to regenerate it.
- **AI voiceover** (OpenAI `gpt-4o-mini-tts`) with a tunable, punchy delivery.
- **Word-by-word karaoke captions** auto-aligned with `faster-whisper`.
- **Music bed** with automatic ducking under the voice.
- **Optional watermark** (your logo + disclaimer) and an **optional branded outro / end card**.
- **Per-platform metadata** — YouTube title + description, TikTok caption, X caption, and hashtags.
- **Batch mode** — generate a week of content from a topic backlog.
- **Local review dashboard** (Flask) — preview, swap clips, pick music, copy captions, download.
- **Niche-agnostic** — set `CONTENT_NICHE` for any subject (finance, fitness, tech, motivation…), or stay purely topic-driven, and swap the writer's whole voice with **prompt presets**.
- **Graceful degradation** — missing an API key or a GPU? The pipeline falls back instead of crashing.

## 🧠 How it works

```
topic ─▶ script (OpenAI, structured JSON)
      ─▶ visuals:  match clip library ──hit──▶ reuse clip
                                     └─miss─▶ generate (Flux image ─▶ Wan motion) ─▶ add to library
      ─▶ voiceover (gpt-4o-mini-tts)
      ─▶ captions (faster-whisper, word-level)
      ─▶ assemble (ffmpeg): Ken Burns / motion + music + watermark + outro
      ─▶ output/{date}-{slug}/final.mp4  +  per-platform titles/descriptions/hashtags
```

Each scene is a cinematic moving image; the only on-screen text is the karaoke captions, so the **voice carries the message**. Output lands in `output/{date}-{slug}/final.mp4` (1080×1920) alongside a `script.json` with all the platform copy.

## 🚀 Quickstart

**Prerequisites:** Python 3.10+ and [FFmpeg](https://ffmpeg.org/download.html) on your `PATH`.

```bash
git clone https://github.com/jadiyeom/Reel-Gen.git
cd Reel-Gen

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium      # for crisp HTML-rendered overlays

cp .env.example .env                        # then add your API keys
python run.py setup                         # one-time: Chromium + overlays
```

Add at least an `OPENAI_API_KEY` to `.env`. Add `FAL_KEY` for AI visuals and/or a free `PEXELS_API_KEY` for stock footage. (No keys at all? The pipeline still runs in an offline smoke-test mode with a sample script and silent timing.)

```bash
python run.py make "why your mornings decide the rest of your day"
# → output/2026-06-24-why-your-mornings.../final.mp4
```

## 🎬 Usage

```bash
python run.py make ["topic"]     # one video on a topic (or auto-pick if omitted)
python run.py make "topic" --aspect-ratio 16:9  # landscape YouTube video
python run.py make-url "https://example.com/article" --aspect-ratio 16:9
python run.py render-external --article-url URL --script PATH --images-dir PATH --aspect-ratio 16:9
python run.py batch 7            # a week's worth from data/topics.txt
python run.py topics import      # load the backlog from data/topics.txt
python run.py fetch-library 20   # pull FREE Pexels/Pixabay stock into the library
python run.py gen-library 10     # AI-generate library clips from library/inventory.csv (fal)
python run.py library-stats      # show library counts / usage
python run.py list               # list generated videos
python run.py serve              # open the review dashboard at http://127.0.0.1:5000
```

Video format defaults to portrait 9:16. Select `--aspect-ratio 16:9` for a 1920×1080 YouTube video; image framing, watermark/outro canvas, and caption sizing/placement follow the selected format. Landscape renders use a `-16x9` output folder suffix so they do not overwrite the portrait version. The dashboard has the same format selector in its create flow.

On Windows you can also double-click **`start.bat`** to launch the dashboard and **`stop.bat`** to shut it down.

### The local review dashboard

`python run.py serve` opens a local web app where you can:

- write/approve/regenerate a script with your own notes,
- **preview which library clip each scene will use and swap it**,
- fetch stock or AI-generate new clips into the library,
- fit a music track over a video and adjust its volume,
- copy the per-platform caption + hashtags and download the MP4.

## 🎨 Two ways to get footage

| Mode | How | Cost | Set in `.env` |
|---|---|---|---|
| **Free Ken Burns** | AI/stock still + zoom/pan motion | free motion | `ANIMATE=none` (default) |
| **Free stock footage** | Pull real clips from Pexels/Pixabay | free | `PEXELS_API_KEY=...` |
| **AI images** | Flux stills via fal.ai | ~$0.025 / image | `IMAGE_BACKEND=fal` |
| **AI motion** | Wan image-to-video via fal.ai | ~$0.15 / clip | `ANIMATE=all` |
| **Local images** | SDXL-Turbo on your GPU | free | `IMAGE_BACKEND=local` (+ `requirements-gpu.txt`) |

The **clip library** ties it together: every generated/fetched clip is embedded and cataloged, so the next time a scene is similar enough it **reuses an existing clip** instead of paying to make a new one (tune `MATCH_THRESHOLD`).

## 💧 Watermark & outro

- **Watermark** (on by default): drop a square `assets/logo/logo.png` and it's overlaid bottom-right on every video; add `BRAND_DISCLAIMER=` for a footer line. Set `WATERMARK=false` to disable. With no logo and no disclaimer, nothing is stamped.
- **Outro / end card** (off by default): set `OUTRO=true` with your `BRAND_NAME`, `BRAND_URL`, `BRAND_TAGLINE`, and `logo.png` to stitch a 3-second branded end card (with a spoken call-to-action) onto every video.

## ⚙️ Configuration

Everything is environment-driven — see [`.env.example`](.env.example) for the full list. Highlights:

| Variable | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | – | Script, voiceover, captions alignment, embeddings |
| `FAL_KEY` | – | AI images (Flux) + AI motion (Wan) |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | – | Free stock footage |
| `IMAGE_BACKEND` | `fal` | `fal` (Flux) or `local` (SDXL on GPU) |
| `ANIMATE` | `none` | `none` (free Ken Burns), `all`, or `N` |
| `CONTENT_NICHE` | – | Focus the writer (e.g. `personal finance`) |
| `SCRIPT_PROMPT` | – | Swap in a custom writer preset from `prompts/presets/` |
| `TTS_VOICE` | `onyx` | OpenAI TTS voice |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` for captions |
| `WATERMARK` / `OUTRO` | `true` / `false` | Toggle the overlays |
| `TARGET_SECONDS` | `30` | Script target guide; actual length varies with story (usually 20–45s) |

Deeper defaults (palette, timings, models, caption styling) live in [`pipeline/config.py`](pipeline/config.py).

### ✍️ Custom script presets

The scriptwriter's persona lives in [`prompts/scriptgen_system.md`](prompts/scriptgen_system.md). Want a different voice or framework? Drop a Markdown file in [`prompts/presets/`](prompts/presets/) and select it by setting `SCRIPT_PROMPT` in `.env` (the filename, without `.md`). One generic example ships there — copy it, make it yours, and switch presets per run. `CONTENT_NICHE` layers a subject focus on top of whichever preset is active.

## 🗂️ Project layout

```
run.py              CLI orchestrator
pipeline/           config, models, scriptgen, images, animate, stock,
                    library, match, voice, captions, assemble, cards, outro
dashboard/          Flask review UI (app.py + templates)
templates/          HTML/CSS for the watermark + outro overlays
prompts/            scriptwriter system prompt + presets/ (swap the writer's voice)
assets/             fonts, your logo, music, generated brand overlays
library/            clip catalog (index.db) + clips/ + images/ + inventory CSVs
data/topics.txt     your topic backlog
output/             generated videos
```

## 💰 Cost per video (rough)

| Setup | What | Approx |
|---|---|---|
| Script + voice + captions only | OpenAI text + TTS | **~$0.02** |
| + free stock or local SDXL stills | Pexels / GPU | ~$0.02 |
| + Flux AI images (5 scenes) | fal images | ~$0.15 |
| + Wan AI motion (5 scenes) | fal motion | ~$0.75 |

Start cheap (`ANIMATE=none`, stock footage) and turn the dials up where it matters.

## ❓ FAQ

**Do I need a GPU?** No. Use `IMAGE_BACKEND=fal` and `WHISPER_DEVICE=cpu`. A GPU only helps for free local SDXL images and faster captions.

**Can I run it 100% free?** Mostly — OpenAI text/TTS is cents per video, and stock footage + Ken Burns motion are free. AI images/motion are the only paid pieces, and they're opt-in.

**Can I publish to YouTube and Instagram?** Yes. The CLI can preview platform-specific copy, then publish a finished reel. YouTube defaults to private; Instagram Reels publish publicly. See the publishing setup below.

## Publishing to social platforms

Publishing is optional. A finished reel can be previewed before upload, and future generations can publish automatically after rendering when you explicitly enable platforms in `.env`.

### YouTube

1. In Google Cloud, enable the [YouTube Data API v3](https://developers.google.com/youtube/v3) and create an OAuth client for a desktop application.
2. Save the downloaded client JSON as `data/youtube_client_secrets.json` (or set `YOUTUBE_CLIENT_SECRETS` to its path).
3. Install project requirements and run `python run.py connect-youtube`. Complete Google sign-in in the browser; the refresh token is stored in `data/youtube_oauth_token.json`.

### Instagram Reels

Instagram publishing uses Meta's Instagram API with Instagram Login. Use the access token generated in Meta Developer Dashboard with `instagram_business_basic` and `instagram_business_content_publish`, and set `INSTAGRAM_ACCESS_TOKEN` plus `INSTAGRAM_BUSINESS_ACCOUNT_ID` in `.env`. This flow uses `https://graph.instagram.com` and Meta fetches the MP4 from a publicly reachable direct video URL; a Facebook Page or Reel permalink is not the MP4 itself. By default, the project uploads the local MP4 to Google Drive, grants temporary Anyone-with-the-link viewer access, passes Drive's download URL to Instagram, then deletes the Drive file after Instagram reports the media upload is finished. Enable the Google Drive API in the same Google Cloud project as your OAuth client and run `python run.py connect-instagram-drive` once to grant the `drive.file` scope. During Instagram's fetch window the video is publicly accessible to anyone holding its link. To use temporary Cloudflare tunnels instead, set `INSTAGRAM_UPLOAD_MODE=tunnel` and install `cloudflared`; to use R2, set `INSTAGRAM_UPLOAD_MODE=r2` and configure `INSTAGRAM_STORAGE_*`. Alternatively, set `INSTAGRAM_VIDEO_URL_TEMPLATE` with `{filename}` (or `{video_id}`), or pass `--instagram-video-url` for one manual publish. Instagram publishes the Reel publicly.

### Facebook Page Reels

Facebook Page publishing uses Meta's Page Reels API and uploads the local MP4 directly. Set `FACEBOOK_PAGE_ID` in `.env`. For automatic renewal, create a Meta app with Facebook Login enabled, configure its Valid OAuth Redirect URI to exactly match `FACEBOOK_OAUTH_REDIRECT_URI` (default `http://localhost:8765/facebook/callback`), and add `FACEBOOK_APP_ID` and `FACEBOOK_APP_SECRET` to `.env`. Keep the App Secret private. The account logging in must have content-creation access to the Page and the app must be allowed to request `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`.

Run `python run.py connect-facebook` once to log in and save the selected Page token locally at `data/facebook_page_token.json` (the token itself is never printed). On a later Reel upload, if Meta reports that this Page token has expired, the publisher opens Meta Login, obtains a new Page token, saves it, and retries the upload once. A Page token in this local file takes precedence over `FACEBOOK_PAGE_ACCESS_TOKEN` in `.env`. You can also reconnect manually at any time with `python run.py connect-facebook`. Meta's Reels API currently documents vertical 9:16 videos of 4–60 seconds for Page Reels; confirm your rendered reel meets the current limits. See [Meta's Facebook Reels publishing flow](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api).

### Preview, publish, or enable automatic publishing

```powershell
# Preview title, description, and caption without connecting to either platform
python run.py publish "output/path/to/final.mp4" --dry-run

# Upload to both platforms; YouTube remains private unless you choose otherwise
python run.py publish "output/path/to/final.mp4" --platform both --privacy-status private --confirm

# Upload to Facebook Page as a Reel
python run.py publish "output/path/to/final.mp4" --platform facebook --confirm

# Publish YouTube as unlisted
python run.py publish "output/path/to/final.mp4" --platform youtube --privacy-status unlisted --confirm
```

To publish every subsequently rendered reel automatically, set `AUTO_PUBLISH_PLATFORMS=youtube,instagram,facebook,x` (or select only the platforms you want) in `.env`. `AUTO_PUBLISH_YOUTUBE_PRIVACY` defaults to `private`. Instagram, Facebook, and X posts are public; each platform must be authorized first. For Instagram Login, the app stages the local file through the selected temporary upload method before Meta fetches it. Leave `AUTO_PUBLISH_PLATFORMS` empty to keep every render in review mode.

The YouTube uploader uses Google's OAuth flow and resumable video upload. Instagram uses Meta's Reel container, processing-status check, and publish flow. See [YouTube video uploads](https://developers.google.com/youtube/v3/guides/uploading_a_video) and [Instagram API documentation](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

### X video posts

X publishing uploads the MP4 in chunks, waits for media processing, then creates a public post with the X-specific short caption. In your X Developer App, enable OAuth 2.0 user authentication with read/write posting permissions and register `http://127.0.0.1:8766/x/callback` as a callback URL. Put the app's Client ID in `X_CLIENT_ID` in `.env`; add `X_CLIENT_SECRET` only if your app type requires one. Run `python run.py connect-x` and authorize the account. Refreshable credentials are saved locally in `data/x_oauth_token.json` and are not printed. X's API plan/access and media rules apply; check your Developer Console for available write access. `python run.py publish VIDEO --platform x --confirm` posts to X. `--platform all` now includes X, while `--platform both` continues to mean YouTube and Instagram.

The implementation follows the current [X media upload flow](https://docs.x.com/x-api/media/upload-media) and [Create Posts endpoint](https://docs.x.com/x-api/posts/create-post). X accepts a single video as a post attachment; the API documentation lists a 20-minute/8-GB limit for a default account and higher caps for Premium/verified accounts.

**What content niche is it for?** Any. Set `CONTENT_NICHE` or just pass topics. The bundled examples are niche-neutral.

## 🤝 Contributing

This started as a weekend project and is shared as-is for anyone to use, fork, or build on. Issues and PRs are welcome — auto-posting backends, new image/i2v models, extra stock sources, and caption styles are all great starting points.

Want to contribute, collaborate, or just say hi? Reach out on **[LinkedIn](https://www.linkedin.com/in/abdullahnaveed0007/)**.

## 📄 License

[MIT](LICENSE) © AbdullahNaveed. Bundled fonts (Inter, Sora) are under the SIL Open Font License — see [`assets/fonts/README.md`](assets/fonts/README.md). You are responsible for the licensing of any stock footage, music, or AI-generated media you produce or redistribute.

---

<sub>Keywords: AI video generator · faceless video generator · short-form video automation · YouTube Shorts generator · TikTok video maker · Instagram Reels automation · text-to-video · AI voiceover · auto captions · fal.ai · Flux · Wan · Stable Diffusion · Pexels stock footage · Python content pipeline.</sub>
