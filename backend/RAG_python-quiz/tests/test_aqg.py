import unittest
from unittest.mock import Mock, patch

from app.utils import aqg
from tests.support import make_chat_client, make_completion_response


class AqgTests(unittest.TestCase):
    def test_maybe_truncate_or_summarize_returns_original_text_when_short(self):
        self.assertEqual(aqg.maybe_truncate_or_summarize(Mock(), "model", "short text"), "short text")

    def test_maybe_truncate_or_summarize_uses_model_when_text_is_long(self):
        response = make_completion_response()
        client = make_chat_client(response)

        with patch("app.utils.aqg.extract_chat_completion_text", return_value="summary"):
            summary = aqg.maybe_truncate_or_summarize(client, "model", "x" * (aqg.MAX_SOURCE_CHARS + 1))

        self.assertEqual(summary, "summary")
        client.chat.completions.create.assert_called_once()

    def test_distribute_counts_handles_empty_remainder_and_small_totals(self):
        cases = (
            (3, [], {}),
            (5, ["remember", "understand", "apply"], {"remember": 2, "understand": 2, "apply": 1}),
            (2, ["remember", "understand", "apply"], {"remember": 1, "understand": 1, "apply": 0}),
        )

        for total, levels, expected in cases:
            with self.subTest(total=total, levels=levels):
                self.assertEqual(aqg.distribute_counts(total, levels), expected)

    def test_build_prompt_uses_fallback_when_all_counts_zero(self):
        prompt = aqg.build_prompt("source", {"remember": 0})
        self.assertIn("generate 1 question", prompt)
        self.assertIn("SOURCE TEXT", prompt)

    def test_build_prompt_includes_selected_levels(self):
        prompt = aqg.build_prompt("source", {"remember": 1, "understand": 2})
        self.assertIn("- remember:", prompt)
        self.assertIn("- understand:", prompt)
