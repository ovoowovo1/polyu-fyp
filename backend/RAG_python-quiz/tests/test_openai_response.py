from types import SimpleNamespace
import unittest

from app.utils import openai_response
from app.utils.openai_response import extract_chat_completion_text


def make_response(*, choices, model="test-model"):
    return SimpleNamespace(model=model, choices=choices)


def make_choice(*, content=None, finish_reason="stop", refusal=None, include_message=True):
    if include_message:
        message = SimpleNamespace(content=content, refusal=refusal)
    else:
        message = None
    return SimpleNamespace(message=message, finish_reason=finish_reason)


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

    def test_raises_when_choices_is_none(self):
        response = make_response(choices=None)

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("choices is None", str(ctx.exception))

    def test_raises_when_choices_is_empty(self):
        response = make_response(choices=[])

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("choices is empty", str(ctx.exception))

    def test_raises_when_response_is_none(self):
        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(None, "unit-test")

        self.assertIn("response is None", str(ctx.exception))

    def test_raises_when_choices_has_unexpected_type(self):
        response = make_response(choices="bad-shape")

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("choices has unexpected type str", str(ctx.exception))

    def test_raises_when_message_is_missing(self):
        response = make_response(choices=[make_choice(include_message=False)])

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("first choice has no message", str(ctx.exception))

    def test_raises_with_refusal_when_content_is_none(self):
        response = make_response(
            choices=[make_choice(content=None, refusal="safety block", finish_reason="content_filter")]
        )

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        message = str(ctx.exception)
        self.assertIn("message.content is None", message)
        self.assertIn("refusal='safety block'", message)
        self.assertIn("finish_reason=content_filter", message)

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

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("contained no text parts", str(ctx.exception))

    def test_raises_for_unexpected_content_type(self):
        response = make_response(choices=[make_choice(content={"unexpected": True})])

        with self.assertRaises(RuntimeError) as ctx:
            extract_chat_completion_text(response, "unit-test")

        self.assertIn("unexpected type dict", str(ctx.exception))
