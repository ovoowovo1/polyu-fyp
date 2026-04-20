from types import SimpleNamespace
import unittest

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
        ]
        response = make_response(choices=[make_choice(content=parts)])

        text = extract_chat_completion_text(response, "unit-test")

        self.assertEqual(text, "Hello world")
