"""Offline end-to-end article render using mocked article, image and voice providers."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from pipeline import config
from pipeline.models import Article, Script
from pipeline.produce import make
from pipeline.assemble import refresh_scene
from pipeline.util import run


def sample_script():
    return Script(
        topic="attention auctions", slug="article-e2e-illustrated",
        scenes=[
            {"index": 1, "narration": "Your attention is being auctioned off.", "image_prompt": "A tiny ink human on an auction block as giant abstract hands bid for glowing attention bubbles.", "scene_type": "image"},
            {"index": 2, "narration": "Each app competes for the same small resource.", "image_prompt": "Three oversized jars pour streams toward one tiny character holding a thimble.", "scene_type": "image"},
            {"index": 3, "narration": "The highest bid is simply your next glance.", "image_prompt": "A character's wandering eye appears as a small prize above a comically tall podium.", "scene_type": "image"},
            {"index": 4, "narration": "", "image_prompt": "", "scene_type": "blank"},
            {"index": 5, "narration": "You can leave the auction by looking away.", "image_prompt": "A tiny character steps off a crowded auction stage into a large calm empty paper field.", "scene_type": "image"},
            {"index": 6, "narration": "The room gets quiet when you stop bidding.", "image_prompt": "Abstract bidders fold into harmless paper shapes as the character walks away.", "scene_type": "image"},
        ], youtube_title="Who is bidding for your attention?", youtube_description="A short visual explanation.",
        tiktok_caption="Your next glance is the prize.", x_caption="Attention is the auction.", hashtags=["attention"])


class ArticleWorkflowE2E(unittest.TestCase):
    def test_article_to_valid_portrait_mp4(self):
        script = sample_script()
        if os.getenv("ARTICLE_E2E_OUTPUT"):
            outdir = Path(os.environ["ARTICLE_E2E_OUTPUT"]).resolve()
            outdir.mkdir(parents=True, exist_ok=True)
        else:
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            outdir = Path(temp.name) / "output"

        def fake_image(prompt, out, style=None):
            img = Image.new("RGB", (576, 1024), "#f5f1e8")
            d = ImageDraw.Draw(img)
            d.ellipse((200, 250, 370, 420), outline="#171717", width=8)
            d.line((285, 420, 285, 670), fill="#171717", width=8)
            d.line((285, 500, 180, 570), fill="#171717", width=8)
            d.line((285, 500, 390, 570), fill="#171717", width=8)
            img.save(out)
            return ""

        def fake_voice(audio_dir, scr):
            info = []
            for i, scene in enumerate(scr.scenes):
                if not scene.narration.strip():
                    # blank scenes are pauses in the voice track
                    duration = 0.65
                    from pipeline.util import run as ff
                    f = audio_dir / f"scene_{scene.index:02d}.mp3"
                    ff(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(duration), "-q:a", "9", str(f)])
                else:
                    duration = [1.9, 2.2, 2.0, 2.4, 2.1][sum(1 for x in scr.scenes[:i] if x.narration.strip()) % 5]
                    f = audio_dir / f"scene_{scene.index:02d}.mp3"
                    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", str(duration), "-q:a", "9", str(f)])
                info.append({"index": scene.index, "path": str(f), "duration": duration + config.SCENE_PAD})
            return info

        words = [{"word": "Your", "start": 0.1, "end": 0.25}, {"word": "attention", "start": 0.26, "end": 0.75},
                 {"word": "is", "start": 0.76, "end": 0.9}, {"word": "being", "start": 0.91, "end": 1.2},
                 {"word": "auctioned", "start": 1.21, "end": 1.65}, {"word": "off.", "start": 1.66, "end": 1.9}]

        article = Article(url="https://example.com/article", title="Attention", content="Article source text " * 60,
                          content_hash="fixture")
        with patch.object(config, "OUTPUT", outdir), \
             patch.object(config, "IMAGE_BACKEND", "local"), \
             patch.object(config, "ENABLE_WATERMARK", False), \
             patch.object(config, "ENABLE_OUTRO", False), \
             patch.object(config, "OPENAI_API_KEY", "mock"), \
             patch("pipeline.articles.extract", return_value=article) as extract, \
             patch("pipeline.images.generate_image", side_effect=fake_image) as gen, \
             patch("pipeline.voice.synthesize", side_effect=fake_voice), \
             patch("pipeline.captions.transcribe_words", return_value=words), \
             patch("pipeline.state.record_video"):
            final = make(None, script=script, article_url=article.url)

        self.assertTrue(final.exists())
        self.assertEqual(extract.call_count, 1)
        self.assertIn(gen.call_count, (0, 5))  # 0 on an unchanged image-cache hit
        self.assertEqual(len(list((final.parent / "scenes").glob("scene_*.png"))), 6)
        self.assertGreater(final.stat().st_size, 20_000)
        timeline = json.loads((final.parent / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(s["scene_type"] != "blank" for s in timeline["scenes"]), 5)
        self.assertTrue(any(s["scene_type"] == "blank" for s in timeline["scenes"]))
        self.assertGreater(timeline["scenes"][2]["end"], timeline["scenes"][2]["start"])
        self.assertTrue((final.parent / "captions.ass").exists())
        captions_before = (final.parent / "captions.ass").read_bytes()
        from pipeline.state import Video
        with patch.object(config, "OUTPUT", outdir):
            video_obj = Video(script.slug, final.parent.name[:10])
            refresh_scene(video_obj, script, 1)
        self.assertEqual(captions_before, (final.parent / "captions.ass").read_bytes())
        import imageio_ffmpeg
        probe = __import__("subprocess").run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(final)], capture_output=True, text=True)
        self.assertIn("1080x1920", probe.stderr)
        self.assertIn("Audio:", probe.stderr)

    def test_extract_removes_navigation_and_ad_content(self):
        from pipeline.articles import extract
        html = """<html><head><title>Article title</title></head><body><nav>Navigation junk</nav><aside>Buy ads</aside>
        <article><h1>Useful article heading</h1><p>""" + ("This is meaningful article text about one useful subject. " * 18) + """</p></article></body></html>"""
        response = unittest.mock.Mock(status_code=200, content=html.encode(), text=html, url="https://example.com/a", is_redirect=False)
        with patch("pipeline.articles._public_url", side_effect=lambda x: x), patch("pipeline.articles.requests.get", return_value=response):
            article = extract("https://example.com/a")
        self.assertIn("Useful article heading", article.content)
        self.assertNotIn("Navigation junk", article.content)
        self.assertNotIn("Buy ads", article.content)


if __name__ == "__main__":
    unittest.main()
