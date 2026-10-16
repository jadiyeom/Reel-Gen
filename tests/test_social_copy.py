"""Unit tests for multi-platform social copy generation."""
from __future__ import annotations

import unittest

from pipeline.models import Script
from pipeline.social_copy import build, _hashtags, _hook


def make_test_script(narration="Why mornings dictate your entire focus. It starts with one habit.", **kwargs):
    scenes = [
        {"index": 1, "narration": narration, "image_prompt": "prompt 1", "scene_type": "image"},
        {"index": 2, "narration": "Second scene narration.", "image_prompt": "prompt 2", "scene_type": "image"},
        {"index": 3, "narration": "Third scene narration.", "image_prompt": "prompt 3", "scene_type": "image"},
        {"index": 4, "narration": "Takeaway payoff line.", "image_prompt": "prompt 4", "scene_type": "image"},
    ]
    data = {
        "topic": "Morning habits",
        "slug": "morning-habits",
        "scenes": scenes,
        "youtube_title": "Why Mornings Dictate Your Entire Day",
        "youtube_description": "A quick visual explanation of morning momentum.",
        "tiktok_caption": "Win the morning, win the day.",
        "x_caption": "Your morning sets the rules.",
        "instagram_caption": "Win the morning to win the day.",
        "hashtags": ["Focus", "MorningRoutine", "Productivity", "Habits", "viral", "#Focus"],
    }
    data.update(kwargs)
    return Script.model_validate(data)


class SocialCopyTests(unittest.TestCase):
    def test_hook_extracts_first_sentence(self):
        script = make_test_script("First sentence here! Second sentence continues.")
        self.assertEqual(_hook(script), "First sentence here!")

    def test_hashtags_deduplicates_and_cleans(self):
        script = make_test_script()
        tags = _hashtags(script, 10)
        self.assertIn("Focus", tags)
        self.assertEqual(len([t for t in tags if t.lower() == "focus"]), 1)
        self.assertNotIn("#Focus", tags)

    def test_build_returns_all_platforms(self):
        script = make_test_script()
        article = {"site_name": "TechDaily", "url": "https://techdaily.com/mornings"}
        copy = build(script, article)

        self.assertIn("youtube", copy)
        self.assertIn("instagram", copy)
        self.assertIn("facebook", copy)
        self.assertIn("x", copy)

        # YouTube checks
        self.assertEqual(copy["youtube"]["title"], script.youtube_title)
        self.assertIn("TechDaily", copy["youtube"]["description"])
        self.assertIn("https://techdaily.com/mornings", copy["youtube"]["description"])
        self.assertLessEqual(len(copy["youtube"]["title"]), 100)
        self.assertLessEqual(len(copy["youtube"]["description"]), 5000)

        # Instagram checks
        self.assertIn("Source: TechDaily", copy["instagram"]["caption"])
        self.assertLessEqual(len(copy["instagram"]["caption"]), 2200)

        # X checks
        self.assertLessEqual(len(copy["x"]["text"]), 280)
        self.assertIn("https://techdaily.com/mornings", copy["x"]["text"])

    def test_long_x_text_is_truncated_safely(self):
        script = make_test_script(
            x_caption="A " * 200,  # very long text
        )
        article = {"url": "https://example.com/very-long-url-path-to-article"}
        copy = build(script, article)
        self.assertLessEqual(len(copy["x"]["text"]), 280)
        self.assertTrue(copy["x"]["text"].endswith("https://example.com/very-long-url-path-to-article"))


if __name__ == "__main__":
    unittest.main()
