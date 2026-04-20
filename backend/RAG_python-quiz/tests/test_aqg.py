import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.utils import aqg


class AqgTests(unittest.TestCase):
    def test_maybe_truncate_or_summarize_returns_original_text_when_short(self):
        self.assertEqual(aqg.maybe_truncate_or_summarize(Mock(), "model", "short text"), "short text")

    def test_maybe_truncate_or_summarize_uses_model_when_text_is_long(self):
        response = SimpleNamespace()
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))

        with patch("app.utils.aqg.extract_chat_completion_text", return_value="summary"):
            summary = aqg.maybe_truncate_or_summarize(client, "model", "x" * (aqg.MAX_SOURCE_CHARS + 1))

        self.assertEqual(summary, "summary")
        client.chat.completions.create.assert_called_once()

    def test_distribute_counts_handles_empty_levels(self):
        self.assertEqual(aqg.distribute_counts(3, []), {})

    def test_distribute_counts_spreads_remainder(self):
        self.assertEqual(
            aqg.distribute_counts(5, ["remember", "understand", "apply"]),
            {"remember": 2, "understand": 2, "apply": 1},
        )

    def test_distribute_counts_handles_total_smaller_than_level_count(self):
        self.assertEqual(
            aqg.distribute_counts(2, ["remember", "understand", "apply"]),
            {"remember": 1, "understand": 1, "apply": 0},
        )

    def test_build_prompt_uses_fallback_when_all_counts_zero(self):
        prompt = aqg.build_prompt("source", {"remember": 0})
        self.assertIn("generate 1 question", prompt)
        self.assertIn("SOURCE TEXT", prompt)

    def test_build_prompt_includes_selected_levels(self):
        prompt = aqg.build_prompt("source", {"remember": 1, "understand": 2})
        self.assertIn("- remember:", prompt)
        self.assertIn("- understand:", prompt)

    def test_read_pdf_to_text_returns_joined_pages(self):
        async def run():
            with patch("app.utils.aqg.extract_text_by_page", return_value=[" page 1 ", "", "page 2"]):
                return await aqg.read_pdf_to_text(b"pdf")

        self.assertEqual(asyncio.run(run()), "page 1\npage 2")

    def test_read_pdf_to_text_raises_http_exception_on_parse_error(self):
        async def run():
            with patch("app.utils.aqg.extract_text_by_page", side_effect=Exception("bad pdf")):
                return await aqg.read_pdf_to_text(b"pdf")

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.status_code, 400)
