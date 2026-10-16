"""Unit tests for the environment healthcheck and doctor tool."""
from __future__ import annotations

import unittest

from pipeline.doctor import check_environment


class DoctorHealthCheckTests(unittest.TestCase):
    def test_check_environment_structure(self):
        result = check_environment()
        self.assertIn("ok", result)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)
        self.assertGreater(len(result["checks"]), 5)

        names = {c["name"] for c in result["checks"]}
        self.assertIn("Python Version", names)
        self.assertIn("FFmpeg", names)
        self.assertIn("faster-whisper", names)
        self.assertIn("Configured TTS Backend", names)
        self.assertIn("Clip Library", names)
        self.assertIn("Default Outro Artwork", names)

        for c in result["checks"]:
            self.assertIn(c["status"], ("pass", "warn", "fail"))
            self.assertTrue(c["message"])


if __name__ == "__main__":
    unittest.main()
