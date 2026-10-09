"""Regression checks for script-generation guidance and Script compatibility."""
import sys
import types
import unittest
from unittest.mock import patch

from pipeline import config, scriptgen
from pipeline.models import Script


def fixture_script(topic: str) -> Script:
    """Representative source-grounded AI-news shape returned by a mock model."""
    if "math" in topic.lower():
        hook = "Did AI just solve math? Not exactly."
        detail = "OpenAI formed an outside group to examine its mathematical research claims."
        payoff = "The question is how to verify a machine's proof, not whether mathematicians vanished."
    elif "enzyme" in topic.lower():
        hook = "Claude found a biological pattern scientists had not recognized."
        detail = "Anthropic reports that researchers identified a sequence resembling a known enzyme system."
        payoff = "Finding the pattern is a lead; it does not yet tell us what the enzyme does."
    else:
        hook = "Could an AI help researchers investigate an outbreak?"
        detail = "Anthropic describes using Claude to help make sense of Ebola-related research."
        payoff = "The useful question is where an assistant speeds research while experts check the evidence."
    narrations = [hook, detail, "That distinction changes what the result actually means.",
                  "The model can surface connections, but a connection still needs testing.", payoff]
    scenes = [
        {"index": i, "narration": line, "image_prompt": f"Conceptual scene {i}",
         "motion_prompt": "Subtle movement", "hero": i == 3}
        for i, line in enumerate(narrations, 1)
    ]
    return Script(
        topic=topic, slug="representative-ai-story", scenes=scenes,
        youtube_title=hook, youtube_description=f"{hook} {detail}",
        tiktok_caption=hook, x_caption=hook, instagram_caption=hook,
        hashtags=["AI", "Research"],
    )


class ScriptGenerationTests(unittest.TestCase):
    def test_multiple_topics_keep_schema_and_receive_updated_story_brief(self):
        topics = [
            "OpenAI mathematics advisory group and proof verification",
            "Anthropic Claude and a newly identified enzyme sequence",
            "Anthropic's Ebola research assistance",
        ]
        for topic in topics:
            with self.subTest(topic=topic):
                calls = []
                result_script = fixture_script(topic)

                class FakeCompletions:
                    def parse(self, **kwargs):
                        calls.append(kwargs)
                        return types.SimpleNamespace(choices=[types.SimpleNamespace(
                            message=types.SimpleNamespace(parsed=result_script)
                        )])

                fake_openai = types.SimpleNamespace(OpenAI=lambda **_: types.SimpleNamespace(
                    beta=types.SimpleNamespace(chat=types.SimpleNamespace(
                        completions=FakeCompletions()
                    ))
                ))
                with patch.object(config, "OPENAI_API_KEY", "mock-key"), \
                     patch.object(config, "TARGET_SECONDS", 30), \
                     patch.object(scriptgen, "_load_system_prompt", return_value=(
                         "One idea. Hook candidates. Truthfulness. Payoff."
                     )), \
                     patch("pipeline.state.list_videos", return_value=[]), \
                     patch.dict(sys.modules, {"openai": fake_openai}):
                    result = scriptgen.generate(topic)

                self.assertEqual(len(calls), 1)
                system_text = calls[0]["messages"][0]["content"]
                user_text = calls[0]["messages"][1]["content"]
                self.assertIn("at least six candidate first sentences", system_text)
                self.assertIn("source support", system_text)
                self.assertIn("deliver the payoff", system_text)
                self.assertIn("20–45 seconds", user_text)
                self.assertIn("guide, not a quota", user_text)
                self.assertIs(calls[0]["response_format"], Script)

                # Verify the returned structured object still provides the exact
                # narration and scene fields consumed by the existing pipeline.
                rebuilt = Script.model_validate(result.model_dump())
                self.assertEqual(rebuilt.scenes[0].narration, result.scenes[0].narration)
                for scene in rebuilt.scenes:
                    self.assertIsInstance(scene.index, int)
                    self.assertTrue(scene.narration)
                    self.assertIsInstance(scene.image_prompt, str)
                    self.assertIsInstance(scene.motion_prompt, str)
                    self.assertIsInstance(scene.hero, bool)
                self.assertTrue(rebuilt.youtube_title)
                self.assertTrue(rebuilt.youtube_description)
                self.assertTrue(rebuilt.tiktok_caption)
                self.assertTrue(rebuilt.x_caption)
                self.assertIsInstance(rebuilt.hashtags, list)

    def test_prompts_reject_rigid_duration_and_unsupported_controversy(self):
        hook = (config.PROMPTS / "hook_policy.md").read_text(encoding="utf-8")
        topic_prompt = (config.PROMPTS / "scriptgen_system.md").read_text(encoding="utf-8")
        article_prompt = (config.PROMPTS / "visual_director_system.md").read_text(encoding="utf-8")
        self.assertIn("at least six candidate", hook)
        self.assertIn("supported", hook)
        self.assertIn("20–45 seconds", topic_prompt)
        self.assertIn("20–45 seconds", article_prompt)
        self.assertNotIn("40–55 total narration words", topic_prompt)
        self.assertNotIn("15–20 second story", topic_prompt)


if __name__ == "__main__":
    unittest.main()
