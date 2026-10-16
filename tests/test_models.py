"""Unit tests for Pydantic models and storyboard schema validation."""
from __future__ import annotations

import unittest
from pydantic import ValidationError

from pipeline.models import Scene, Script, Timeline, TimelineScene, Article


class ModelsTests(unittest.TestCase):
    def test_valid_standard_script(self):
        scenes = [
            {"index": i, "narration": f"Narration for scene {i}", "image_prompt": f"Prompt {i}", "scene_type": "image"}
            for i in range(1, 6)
        ]
        script = Script.model_validate({
            "topic": "Test topic",
            "slug": "test-topic",
            "scenes": scenes,
            "youtube_title": "Title",
            "youtube_description": "Description",
            "tiktok_caption": "Caption",
            "x_caption": "X copy",
            "hashtags": ["test"],
        })
        self.assertEqual(len(script.scenes), 5)
        self.assertEqual(script.slug, "test-topic")

    def test_standard_script_rejects_fewer_than_4_illustrations(self):
        scenes = [
            {"index": i, "narration": f"Narration {i}", "image_prompt": f"Prompt {i}", "scene_type": "image"}
            for i in range(1, 4)
        ]
        with self.assertRaises(ValidationError):
            Script.model_validate({
                "topic": "Too few",
                "slug": "too-few",
                "scenes": scenes,
                "youtube_title": "T",
                "youtube_description": "D",
                "tiktok_caption": "C",
                "x_caption": "X",
                "hashtags": [],
            })

    def test_extended_storyboard_allows_more_scenes(self):
        scenes = [
            {"index": i, "narration": f"Narration {i}", "image_prompt": f"Prompt {i}", "scene_type": "image"}
            for i in range(1, 20)
        ]
        script = Script.model_validate({
            "topic": "Extended story",
            "slug": "extended-story",
            "scenes": scenes,
            "youtube_title": "Title",
            "youtube_description": "Description",
            "tiktok_caption": "Caption",
            "x_caption": "X copy",
            "hashtags": ["extended"],
        }, context={"allow_extended_storyboard": True})
        self.assertEqual(len(script.scenes), 19)

    def test_timeline_validation(self):
        tl = Timeline(
            scenes=[
                TimelineScene(index=1, scene_type="image", start=0.0, end=2.5, narration="Line 1"),
                TimelineScene(index=2, scene_type="blank", start=2.5, end=3.1, narration=""),
            ],
            duration=3.1,
        )
        self.assertEqual(len(tl.scenes), 2)
        self.assertEqual(tl.duration, 3.1)


if __name__ == "__main__":
    unittest.main()
