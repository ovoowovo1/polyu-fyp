from types import SimpleNamespace
import unittest

from app.utils import openai_response
from app.utils.openai_response import extract_chat_completion_text
from tests.support import make_openai_choice as make_choice
from tests.support import make_openai_response as make_response


def assert_extract_error(testcase, response, expected_parts):
    expected_parts = expected_parts if isinstance(expected_parts, tuple) else (expected_parts,)
    with testcase.assertRaises(RuntimeError) as ctx:
        extract_chat_completion_text(response, "unit-test")

    message = str(ctx.exception)
    for expected in expected_parts:
        testcase.assertIn(expected, message)


class ExtractChatCompletionTextTests(unittest.TestCase):
    def test_truncate_text_and_safe_repr_cover_edge_cases(self):
        self.assertEqual(openai_response._truncate_text(None), "None")
        self.assertEqual(openai_response._truncate_text("abcdef", limit=5), "ab...")

        class BadRepr:
            def __repr__(self):
                raise RuntimeError("boom")

        self.assertIn("unrepresentable", openai_response._safe_repr(BadRepr(), limit=30))
        self.assertEqual(openai_response._safe_repr("abcdef", limit=5), "'a...")

    def test_build_response_summary_covers_none_non_list_and_content_variants(self):
        self.assertEqual(openai_response._build_response_summary(None), "response=None")

        summary = openai_response._build_response_summary(
            SimpleNamespace(model="test-model", choices="bad-shape")
        )
        self.assertIn("choices_type=str", summary)

        string_summary = openai_response._build_response_summary(
            make_response(choices=[make_choice(content="plain text")])
        )
        self.assertIn("content_preview='plain text'", string_summary)

        list_summary = openai_response._build_response_summary(
            make_response(choices=[make_choice(content=[{"type": "text", "text": "hello"}], refusal="nope")])
        )
        self.assertIn("content_parts=1", list_summary)
        self.assertIn("refusal='nope'", list_summary)

        object_summary = openai_response._build_response_summary(
            make_response(choices=[make_choice(content=SimpleNamespace(value="x"))])
        )
        self.assertIn("content_preview=", object_summary)

    def test_returns_plain_string_content(self):
        response = make_response(choices=[make_choice(content='{"ok": true}')])

        text = extract_chat_completion_text(response, "unit-test")

        self.assertEqual(text, '{"ok": true}')

    def test_raises_for_invalid_response_shapes(self):
        cases = [
            (None, "response is None"),
            (make_response(choices=None), "choices is None"),
            (make_response(choices=[]), "choices is empty"),
            (make_response(choices="bad-shape"), "choices has unexpected type str"),
            (make_response(choices=[make_choice(include_message=False)]), "first choice has no message"),
            (
                make_response(choices=[make_choice(content=None, refusal="safety block", finish_reason="content_filter")]),
                ("message.content is None", "refusal='safety block'", "finish_reason=content_filter"),
            ),
        ]
        for response, expected_parts in cases:
            with self.subTest(expected_parts=expected_parts):
                assert_extract_error(self, response, expected_parts)

    def test_concatenates_text_parts_from_content_list(self):
        parts = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "ignored"}},
            SimpleNamespace(type="text", text=" world"),
            SimpleNamespace(type=None, text="!"),
        ]
        response = make_response(choices=[make_choice(content=parts)])

        text = extract_chat_completion_text(response, "unit-test")

        self.assertEqual(text, "Hello world!")

    def test_raises_for_content_list_without_text(self):
        response = make_response(choices=[make_choice(content=[{"type": "image_url", "image_url": {"url": "ignored"}}])])

        assert_extract_error(self, response, "contained no text parts")

    def test_raises_for_unexpected_content_type(self):
        response = make_response(choices=[make_choice(content={"unexpected": True})])

        assert_extract_error(self, response, "unexpected type dict")
