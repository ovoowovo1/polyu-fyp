import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.llm import structured_json


def make_chat_client(*responses):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(side_effect=list(responses)))
        )
    )


class StructuredJsonFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_structured_json_gemini_json_schema_success_unchanged(self):
        client = make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="google/gemini-2.5-flash",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value='{"ok": true}',
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await structured_json.generate_structured_json(
                "prompt",
                {"type": "object", "required": ["ok"]},
                operation_name="structured",
                system_prompt="system",
                temperature=0.2,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.chat.completions.create.call_count, 1)
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(create_kwargs["temperature"], 0.2)
        self.assertEqual(create_kwargs["response_format"]["type"], "json_schema")

    async def test_generate_structured_json_empty_choices_falls_back_to_plain_json(self):
        client = make_chat_client(
            SimpleNamespace(choices=None),
            SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]),
        )

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="openrouter/model-without-json-schema",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            side_effect=["", '{"ok": true}'],
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await structured_json.generate_structured_json(
                "prompt",
                {"type": "object", "required": ["ok"]},
                operation_name="structured",
                system_prompt="base system",
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.chat.completions.create.call_count, 2)
        first_kwargs = client.chat.completions.create.call_args_list[0].kwargs
        second_kwargs = client.chat.completions.create.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["response_format"]["type"], "json_schema")
        self.assertNotIn("response_format", second_kwargs)
        self.assertIn("base system", second_kwargs["messages"][0]["content"])
        self.assertIn("Return only valid JSON matching this schema", second_kwargs["messages"][0]["content"])

    async def test_generate_structured_json_falls_back_on_invalid_structured_output(self):
        client = make_chat_client(
            SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]),
            SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]),
        )

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="openrouter/model-without-json-schema",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            side_effect=['{"wrong": true}', '{"ok": true}'],
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await structured_json.generate_structured_json(
                "prompt",
                {"type": "object", "required": ["ok"]},
                operation_name="structured",
            )

        self.assertEqual(result, {"ok": True})

    async def test_generate_structured_json_deepseek_plain_json_fenced_block_parses(self):
        client = make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="deepseek/deepseek-v4-flash",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value='```json\n{"ok": true}\n```',
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await structured_json.generate_structured_json(
                "prompt",
                {"type": "object", "required": ["ok"]},
                operation_name="structured",
            )

        self.assertEqual(result, {"ok": True})
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertNotIn("response_format", create_kwargs)
        self.assertIn("Return only valid JSON matching this schema", create_kwargs["messages"][0]["content"])

    async def test_generate_structured_json_invalid_plain_json_raises_clear_runtime_error(self):
        client = make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="deepseek/deepseek-v4-flash",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value="not-json",
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                await structured_json.generate_structured_json(
                    "prompt",
                    {"type": "object", "required": ["ok"]},
                    operation_name="structured",
                )

    async def test_generate_structured_json_non_object_plain_json_raises_clear_runtime_error(self):
        client = make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="deepseek/deepseek-v4-flash",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value="[]",
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            with self.assertRaisesRegex(RuntimeError, "not an object"):
                await structured_json.generate_structured_json(
                    "prompt",
                    {"type": "object"},
                    operation_name="structured",
                )
