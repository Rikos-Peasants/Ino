"""Tests for the AI fallback chain, subtitle parsing, and the rep ladder."""

import unittest

from models.ai_router import AIRouter
from models.inorep_status import INOREP_TIERS, get_inorep_tier
from models.rep_economy import (
    next_tier_for,
    progress_bar,
    tier_for,
    tier_label,
)
from models.youtube_transcript import extract_video_id, parse_timedtext


class ExtractVideoIdTests(unittest.TestCase):
    def test_accepts_common_url_shapes(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?list=X&v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "dQw4w9WgXcQ": "dQw4w9WgXcQ",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(extract_video_id(url), expected)

    def test_rejects_non_youtube_input(self):
        self.assertIsNone(extract_video_id("https://example.com/video"))
        self.assertIsNone(extract_video_id(""))


class ParseTimedtextTests(unittest.TestCase):
    def test_parses_srv3_xml_with_nested_segments(self):
        raw = (
            '<?xml version="1.0" encoding="utf-8" ?><timedtext format="3"><body>'
            '<p t="0" d="100">Hello there</p>'
            '<p t="100" d="100"><s>general</s><s> kenobi</s></p>'
            "</body></timedtext>"
        )
        self.assertEqual(parse_timedtext(raw), "Hello there general kenobi")

    def test_parses_json3(self):
        raw = (
            '{"events":[{"segs":[{"utf8":"first "},{"utf8":"line"}]},'
            '{"segs":[{"utf8":"second line"}]}]}'
        )
        self.assertEqual(parse_timedtext(raw), "first line second line")

    def test_strips_caption_noise(self):
        raw = (
            '<?xml version="1.0"?><timedtext><body>'
            "<p>[Music] real words [Applause]</p></body></timedtext>"
        )
        self.assertEqual(parse_timedtext(raw), "real words")

    def test_returns_none_for_empty_or_broken_input(self):
        self.assertIsNone(parse_timedtext(""))
        self.assertIsNone(parse_timedtext("not xml at all <<<"))


class OpenRouterExtractionTests(unittest.TestCase):
    def test_reads_plain_content(self):
        data = {"choices": [{"message": {"content": "  hello  "}}]}
        self.assertEqual(AIRouter._extract_openrouter_text(data), "hello")

    def test_reads_block_list_content(self):
        data = {
            "choices": [
                {"message": {"content": [{"type": "text", "text": "a"}, {"text": "b"}]}}
            ]
        }
        self.assertEqual(AIRouter._extract_openrouter_text(data), "ab")

    def test_falls_back_to_reasoning_when_content_is_null(self):
        # glm-* returns content=null when the whole budget went to thinking.
        data = {"choices": [{"message": {"content": None, "reasoning": "thought"}}]}
        self.assertEqual(AIRouter._extract_openrouter_text(data), "thought")

    def test_handles_empty_choices(self):
        self.assertEqual(AIRouter._extract_openrouter_text({"choices": []}), "")


class TranscriptPromptTests(unittest.TestCase):
    def test_prompt_is_unchanged_without_a_transcript(self):
        prompt = "describe this"
        self.assertIs(AIRouter._with_transcript(prompt, "url", None), prompt)
        self.assertIs(AIRouter._with_transcript(prompt, "url", "   "), prompt)

    def test_transcript_is_appended_and_labelled(self):
        result = AIRouter._with_transcript("describe", "http://v", "spoken words")
        self.assertIn("describe", result)
        self.assertIn("spoken words", result)
        self.assertIn("http://v", result)
        self.assertIn("TRANSCRIPT", result)


class RepTierTests(unittest.TestCase):
    """rep_economy must agree with the canonical ladder, not invent its own."""

    def test_delegates_to_the_canonical_ladder(self):
        # A second, shorter ladder used to live in config.py, which made /rep
        # disagree with /inorep check about what rank someone held.
        for rep in (-5000, -100, 0, 1, 45, 100, 800, 2000, 10000):
            with self.subTest(rep=rep):
                self.assertEqual(tier_for(rep), get_inorep_tier(rep))

    def test_known_tier_names(self):
        self.assertEqual(tier_for(0)["status"], "\U0001f610 Neutral")
        self.assertEqual(tier_for(45)["status"], "\u2b50 Ino's Friend")
        self.assertEqual(tier_for(10000)["status"], "\U0001f320 Ino's Mythic Constellation")

    def test_next_tier_is_the_next_threshold_up(self):
        self.assertEqual(next_tier_for(0)["threshold"], 1)
        self.assertEqual(next_tier_for(45)["threshold"], 60)
        self.assertEqual(next_tier_for(800)["threshold"], 1000)

    def test_no_next_tier_at_the_top(self):
        self.assertIsNone(next_tier_for(10000))
        self.assertIsNone(next_tier_for(99999))

    def test_tier_label_is_the_status_string(self):
        self.assertEqual(tier_label(tier_for(45)), tier_for(45)["status"])

    def test_every_tier_carries_what_the_ui_needs(self):
        for tier in INOREP_TIERS:
            with self.subTest(tier=tier["status"]):
                for field in ("threshold", "status", "relationship", "color", "message"):
                    self.assertIn(field, tier)

    def test_progress_bar_is_fixed_width_and_clamped(self):
        for current, target in [(0, 10), (5, 10), (10, 10), (99, 10), (-5, 10)]:
            with self.subTest(current=current):
                self.assertEqual(len(progress_bar(current, target)), 12)
        self.assertEqual(progress_bar(0, 10).count("\u2588"), 0)
        self.assertEqual(progress_bar(10, 10).count("\u2588"), 12)
        self.assertEqual(progress_bar(0, 0), "\u2588" * 12)


if __name__ == "__main__":
    unittest.main()
