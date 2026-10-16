from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from pipeline import cards, config
from pipeline.end_card import append_outro_image_to_video, resolve_outro_image
from pipeline.util import ffprobe_duration, run


class FollowEndCardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uploaded_logo_overrides_configured_default(self):
        uploaded = self.tmp_path / "uploaded.png"
        uploaded_bytes = b"uploaded-logo-bytes"
        uploaded.write_bytes(uploaded_bytes)
        default = self.tmp_path / "default.png"
        default.write_bytes(b"default-logo-bytes")
        with patch.object(config, "LOGO_PNG", default):
            expected = "data:image/png;base64," + base64.b64encode(uploaded_bytes).decode()
            self.assertEqual(cards._logo_data_uri(uploaded), expected)

    def test_committed_backspace_outro_is_present_and_readable(self):
        self.assertTrue(config.DEFAULT_OUTRO_IMAGE.is_file())
        with Image.open(config.DEFAULT_OUTRO_IMAGE) as image:
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)
            image.verify()

    def test_default_backspace_art_is_used_when_no_custom_outro(self):
        default = self.tmp_path / "backspace_outro.webp"
        default.write_bytes(b"default-outro")
        with patch.object(config, "DEFAULT_OUTRO_IMAGE", default):
            self.assertEqual(resolve_outro_image(), default)

    def test_custom_outro_image_overrides_default(self):
        default = self.tmp_path / "backspace_outro.webp"
        default.write_bytes(b"default-outro")
        custom = self.tmp_path / "my-outro.png"
        custom.write_bytes(b"custom-outro")
        with patch.object(config, "DEFAULT_OUTRO_IMAGE", default):
            self.assertEqual(resolve_outro_image(custom), custom.resolve())

    def test_missing_default_outro_fails_clearly(self):
        with patch.object(config, "DEFAULT_OUTRO_IMAGE", self.tmp_path / "missing.webp"):
            with self.assertRaises(FileNotFoundError) as ctx:
                resolve_outro_image()
            self.assertRegex(str(ctx.exception), r"(?i)default|restore|outro image")

    def test_append_outro_image_to_video_produces_valid_output(self):
        # Create a small valid test video and image
        test_video = self.tmp_path / "test_input.mp4"
        run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "1.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            str(test_video),
        ])
        self.assertTrue(test_video.is_file())
        orig_dur = ffprobe_duration(test_video)
        self.assertAlmostEqual(orig_dur, 1.0, delta=0.3)

        with patch.object(config, "OUTRO_SECONDS", 2.0):
            result = append_outro_image_to_video(test_video)
        self.assertEqual(result, test_video)
        self.assertTrue(result.is_file())
        final_dur = ffprobe_duration(result)
        # 1.0s input + 2.0s outro = ~3.0s
        self.assertGreater(final_dur, 2.5)


if __name__ == "__main__":
    unittest.main()
