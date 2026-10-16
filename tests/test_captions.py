"""Unit tests for the caption formatting, alignment, and ASS styling."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from pipeline import captions, config


class CaptionsFormattingTests(unittest.TestCase):
    def test_cc_time_formatting(self):
        self.assertEqual(captions._cc(0.0), "0:00:00.00")
        self.assertEqual(captions._cc(1.25), "0:00:01.25")
        self.assertEqual(captions._cc(65.5), "0:01:05.50")
        self.assertEqual(captions._cc(3661.05), "1:01:01.05")
        self.assertEqual(captions._cc(-5.0), "0:00:00.00")

    def test_hex_to_ass(self):
        # #RRGGBB -> &HAABBGGRR&
        # #C9573F -> Red=C9, Green=57, Blue=3F -> &H003F57C9&
        self.assertEqual(captions._hex_to_ass("#C9573F"), "&H003F57C9&")
        self.assertEqual(captions._hex_to_ass("#FFFFFF"), "&H00FFFFFF&")
        self.assertEqual(captions._hex_to_ass("#000000", alpha="80"), "&H80000000&")

    def test_group_respects_limits_and_sentence_stops(self):
        words = [
            {"word": "This", "start": 0.0, "end": 0.2},
            {"word": "is", "start": 0.25, "end": 0.4},
            {"word": "a", "start": 0.45, "end": 0.55},
            {"word": "sentence.", "start": 0.6, "end": 0.9},
            {"word": "Next", "start": 1.0, "end": 1.2},
            {"word": "one", "start": 1.25, "end": 1.4},
            {"word": "starts.", "start": 1.45, "end": 1.8},
        ]
        with patch.object(config, "CAPTION_MAX_WORDS", 4), \
             patch.object(config, "CAPTION_MAX_CHARS", 30):
            groups = captions._group(words)
            self.assertEqual(len(groups), 2)
            self.assertEqual([w["word"] for w in groups[0]], ["This", "is", "a", "sentence."])
            self.assertEqual([w["word"] for w in groups[1]], ["Next", "one", "starts."])

    def test_group_breaks_on_significant_silence_gap(self):
        words = [
            {"word": "First", "start": 0.0, "end": 0.3},
            {"word": "scene", "start": 0.35, "end": 0.6},
            # Gap of 0.8 seconds (> 0.55s threshold)
            {"word": "Second", "start": 1.4, "end": 1.7},
            {"word": "scene", "start": 1.75, "end": 2.0},
        ]
        groups = captions._group(words)
        self.assertEqual(len(groups), 2)
        self.assertEqual([w["word"] for w in groups[0]], ["First", "scene"])
        self.assertEqual([w["word"] for w in groups[1]], ["Second", "scene"])

    def test_norm_strips_punctuation_and_lowercases(self):
        self.assertEqual(captions._norm("Attention!"), "attention")
        self.assertEqual(captions._norm("don't"), "don't")
        self.assertEqual(captions._norm("  #Focus--  "), "focus")

    def test_align_to_script_replaces_spelling_preserving_timing(self):
        whisper_words = [
            {"word": "yer", "start": 0.1, "end": 0.3},
            {"word": "attenshun", "start": 0.35, "end": 0.8},
            {"word": "matters", "start": 0.85, "end": 1.2},
        ]
        true_text = "Your attention matters"
        aligned = captions._align_to_script(whisper_words, true_text)
        self.assertEqual(len(aligned), 3)
        self.assertEqual([w["word"] for w in aligned], ["Your", "attention", "matters"])
        self.assertEqual(aligned[0]["start"], 0.1)
        self.assertEqual(aligned[1]["end"], 0.8)

    def test_emphasis_words_highlighting_in_dialogue(self):
        line = [
            {"word": "Focus", "start": 0.0, "end": 0.4},
            {"word": "on", "start": 0.45, "end": 0.6},
            {"word": "results.", "start": 0.65, "end": 1.0},
        ]
        with patch.object(config, "CAPTION_EMPHASIS_WORDS", {"focus", "results"}):
            dialogue = captions._dialogue(line, position="bottom")
            # Face dialogue should contain color override tags
            self.assertIn("Dialogue: 1,", dialogue)
            self.assertIn(r"{\c", dialogue)
            self.assertIn("Focus", dialogue)

    def test_dialogue_positions(self):
        line = [{"word": "Test", "start": 0.0, "end": 0.5}]
        for pos in ("top", "middle", "bottom"):
            res = captions._dialogue(line, position=pos)
            self.assertIn("Dialogue: 0,", res)
            self.assertIn("Dialogue: 1,", res)

    def test_cuda_fallback_and_cache_eviction(self):
        captions._CUDA_WHISPER_AVAILABLE = None
        captions._WHISPER_MODELS.clear()
        fake_cuda_model = object()
        captions._WHISPER_MODELS[(config.WHISPER_MODEL, "cuda", "float16")] = fake_cuda_model

        def mock_run_whisper(audio_path, device, compute):
            if device == "cuda":
                raise RuntimeError("CUDA failed")
            return [{"word": "hello", "start": 0.0, "end": 0.5}]

        with patch.object(config, "WHISPER_DEVICE", "cuda"), \
             patch("pipeline.captions._run_whisper", side_effect=mock_run_whisper):
            words = captions.transcribe_words("dummy.wav")
            self.assertEqual(len(words), 1)
            self.assertEqual(captions._CUDA_WHISPER_AVAILABLE, False)
            self.assertNotIn((config.WHISPER_MODEL, "cuda", "float16"), captions._WHISPER_MODELS)

    def test_subsequent_call_skips_cuda_once_failed(self):
        captions._CUDA_WHISPER_AVAILABLE = False
        devices_called = []

        def mock_run_whisper(audio_path, device, compute):
            devices_called.append(device)
            return [{"word": "test", "start": 0.0, "end": 0.5}]

        with patch.object(config, "WHISPER_DEVICE", "cuda"), \
             patch("pipeline.captions._run_whisper", side_effect=mock_run_whisper):
            captions.transcribe_words("dummy.wav")
            self.assertEqual(devices_called, ["cpu"])


if __name__ == "__main__":
    unittest.main()
