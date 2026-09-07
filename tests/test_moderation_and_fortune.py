"""Tests for duration parsing, alert-target recovery, polls and fortunes."""

import unittest
from datetime import timedelta

from models.fortune_teller import (
    STATIC_FORTUNES,
    FortuneTeller,
    static_fortune_for,
)
from models.mod_actions import MAX_TIMEOUT, format_duration, parse_duration
from views.mod_action_view import AlertActionView


class ParseDurationTests(unittest.TestCase):
    def test_single_units(self):
        cases = {
            "30s": timedelta(seconds=30),
            "5m": timedelta(minutes=5),
            "2h": timedelta(hours=2),
            "7d": timedelta(days=7),
            "1w": timedelta(weeks=1),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), expected)

    def test_compound_and_spacing(self):
        self.assertEqual(parse_duration("1d12h"), timedelta(days=1, hours=12))
        self.assertEqual(parse_duration("2h 30m"), timedelta(hours=2, minutes=30))
        self.assertEqual(parse_duration("1W"), timedelta(weeks=1))

    def test_rejects_junk_and_zero(self):
        # None means "unparseable", which callers report differently from zero.
        for text in ("", "banana", "0", "0m", "   ", "d"):
            with self.subTest(text=text):
                self.assertIsNone(parse_duration(text))

    def test_timeout_ceiling(self):
        self.assertLessEqual(parse_duration("28d"), MAX_TIMEOUT)
        self.assertGreater(parse_duration("29d"), MAX_TIMEOUT)
        self.assertGreater(parse_duration("5w"), MAX_TIMEOUT)


class FormatDurationTests(unittest.TestCase):
    def test_largest_units_first_and_capped_at_two(self):
        self.assertEqual(format_duration(timedelta(days=1, hours=12)), "1 day 12 hours")
        self.assertEqual(format_duration(timedelta(minutes=1, seconds=30)), "1 minute 30 seconds")
        self.assertEqual(format_duration(timedelta(weeks=1)), "1 week")

    def test_singular_and_zero(self):
        self.assertEqual(format_duration(timedelta(hours=1)), "1 hour")
        self.assertEqual(format_duration(timedelta(0)), "0 seconds")
        self.assertEqual(format_duration(timedelta(seconds=-5)), "0 seconds")


class AlertTargetRecoveryTests(unittest.TestCase):
    """The buttons must still know their subject after a restart."""

    def _extract(self, footer):
        match = AlertActionView.FOOTER_PATTERN.search(footer)
        return int(match.group(1)) if match else None

    def test_recovers_id_from_footer(self):
        self.assertEqual(
            self._extract("User ID: 226050139226112000 · Message ID: 999"),
            226050139226112000,
        )
        self.assertEqual(self._extract("User ID: 784822151529627708"), 784822151529627708)

    def test_ignores_footers_without_a_user_id(self):
        self.assertIsNone(self._extract("Message ID: 12345"))
        self.assertIsNone(self._extract(""))

    def test_does_not_match_a_short_number(self):
        # Snowflakes are 17-19 digits; a stray small number is not an ID.
        self.assertIsNone(self._extract("User ID: 42"))


class FortuneTests(unittest.TestCase):
    def test_static_pool_is_substantial_and_unique(self):
        self.assertGreaterEqual(len(STATIC_FORTUNES), 50)
        self.assertEqual(len(set(STATIC_FORTUNES)), len(STATIC_FORTUNES))

    def test_every_static_fortune_is_a_complete_sentence(self):
        for fortune in STATIC_FORTUNES:
            with self.subTest(fortune=fortune):
                self.assertTrue(fortune.endswith((".", "!", "?", "…")))

    def test_static_pick_is_stable_per_user_per_day(self):
        first = static_fortune_for("123", "2026-09-07")
        self.assertEqual(first, static_fortune_for("123", "2026-09-07"))

    def test_static_pick_varies_by_user_and_day(self):
        same_day = {static_fortune_for(str(uid), "2026-09-07") for uid in range(40)}
        self.assertGreater(len(same_day), 5)
        across_days = {static_fortune_for("123", f"2026-09-{d:02d}") for d in range(1, 29)}
        self.assertGreater(len(across_days), 5)

    def test_clean_strips_wrappers(self):
        clean = FortuneTeller._clean
        self.assertEqual(clean('  "A quiet day approaches."  '), "A quiet day approaches.")
        self.assertEqual(clean("Fortune: A quiet day approaches."), "A quiet day approaches.")
        self.assertEqual(
            clean("Today's fortune: A quiet day approaches."), "A quiet day approaches."
        )

    def test_clean_rejects_truncated_output(self):
        # The exact failure seen in practice: the model spends its budget
        # thinking and the fortune stops mid-sentence.
        self.assertIsNone(FortuneTeller._clean("You left the last stitch undone,"))
        self.assertIsNone(FortuneTeller._clean("An unsent draft from"))

    def test_clean_rejects_empty_and_overlong(self):
        self.assertIsNone(FortuneTeller._clean(""))
        self.assertIsNone(FortuneTeller._clean("Hi."))
        self.assertIsNone(FortuneTeller._clean("word " * 100 + "."))

    def test_clean_keeps_only_the_first_line(self):
        self.assertEqual(
            FortuneTeller._clean("A quiet day approaches.\nSomething else entirely."),
            "A quiet day approaches.",
        )


if __name__ == "__main__":
    unittest.main()
