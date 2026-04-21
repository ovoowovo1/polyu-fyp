import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests
from fastapi import HTTPException

from app.utils import api_key_manager
from app.utils.ingest_errors import EmbeddingProviderError


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, text="", reason="OK", json_error=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = reason
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeChatModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return {"schema": schema, "kwargs": self.kwargs}


class ApiKeyManagerBase(unittest.TestCase):
    def setUp(self):
        self.original_keys = list(api_key_manager._keys)
        self.original_index = api_key_manager._index

    def tearDown(self):
        api_key_manager._keys = self.original_keys
        api_key_manager._index = self.original_index


class KeyManagementTests(ApiKeyManagerBase):
    def test_key_initialization_and_rotation(self):
        api_key_manager._keys = []
        api_key_manager._index = 99

        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(google_api_key_list=" key-1, ,key-2 "),
        ):
            self.assertEqual(api_key_manager.get_keys_count(), 2)
            self.assertEqual(api_key_manager.get_current_api_key(), "key-1")
            self.assertTrue(api_key_manager.switch_to_next_key())
            self.assertEqual(api_key_manager.get_current_api_key(), "key-2")
            self.assertFalse(api_key_manager.switch_to_next_key())
            self.assertIsNone(api_key_manager.get_current_api_key())
            api_key_manager.reset_key_index()
            self.assertEqual(api_key_manager.get_current_api_key(), "key-1")

    def test_get_genai_client_and_default_model_name(self):
        api_key_manager._keys = ["current-key"]
        api_key_manager._index = 0

        with patch("app.utils.api_key_manager.OpenAI", return_value="client") as openai_cls:
            client = api_key_manager.get_genai_client()
        self.assertEqual(client, "client")
        self.assertEqual(openai_cls.call_args.kwargs["api_key"], "current-key")
        self.assertEqual(openai_cls.call_args.kwargs["base_url"], api_key_manager.OPENROUTER_BASE_URL)

        with patch("app.utils.api_key_manager.OpenAI", return_value="client") as openai_cls:
            api_key_manager.get_genai_client("explicit-key")
        self.assertEqual(openai_cls.call_args.kwargs["api_key"], "explicit-key")

        api_key_manager._keys = []
        api_key_manager._index = 0
        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(google_api_key_list="", google_ai_model=""),
        ):
            with self.assertRaises(RuntimeError):
                api_key_manager.get_genai_client()

        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(google_ai_model="", google_api_key_list=""),
        ):
            self.assertEqual(api_key_manager.get_default_model_name(), "gemini-2.5-flash")

    def test_small_helpers_cover_mask_provider_safe_int_and_retryability(self):
        self.assertEqual(api_key_manager._mask_key(None), "<EMPTY>")
        self.assertEqual(api_key_manager._mask_key("short"), "short")
        self.assertEqual(api_key_manager._mask_key("abcdefghijklmnop"), "abcd...mnop")

        self.assertEqual(api_key_manager._provider_name_from_base_url("https://openrouter.ai/api/v1"), "openrouter")
        self.assertEqual(api_key_manager._provider_name_from_base_url("https://api.example.com/v1"), "api.example.com")
        self.assertEqual(api_key_manager._provider_name_from_base_url("not-a-url"), "openai-compatible")

        self.assertEqual(api_key_manager._safe_int(3), 3)
        self.assertEqual(api_key_manager._safe_int("42"), 42)
        self.assertIsNone(api_key_manager._safe_int(True))
        self.assertIsNone(api_key_manager._safe_int("4a"))

        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=None,
                upstream_code=None,
                upstream_message="No successful provider responses returned",
            )
        )
        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=None,
                upstream_code=None,
                upstream_message="No endpoints found for provider",
            )
        )
        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=404,
                upstream_code=None,
                upstream_message="missing",
            )
        )
        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=None,
                upstream_code=404,
                upstream_message="missing",
            )
        )
        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=503,
                upstream_code=None,
                upstream_message="server error",
            )
        )
        self.assertTrue(
            api_key_manager._is_retryable_provider_error(
                http_status=None,
                upstream_code="429",
                upstream_message="rate limited",
            )
        )
        self.assertFalse(
            api_key_manager._is_retryable_provider_error(
                http_status=400,
                upstream_code="bad",
                upstream_message="validation failed",
            )
        )


class EmbeddingsTests(ApiKeyManagerBase):
    def setUp(self):
        super().setUp()
        self.settings = SimpleNamespace(
            openai_embedding_api_key="embed-key",
            openai_embedding_base_url="https://embed.example.com/v1/",
            openai_embedding_model="embed-model",
            openai_embedding_fallback_model="fallback-model",
            google_ai_model="flash-model",
            google_api_key_list="key-1,key-2",
        )

    def test_embedding_model_init_endpoint_and_factory_helpers(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=self.settings), patch(
            "app.utils.api_key_manager.OpenAI",
            return_value="openai-client",
        ):
            model = api_key_manager.OpenAIEmbeddings()

        self.assertEqual(model.client, "openai-client")
        self.assertEqual(model.base_url, "https://embed.example.com/v1")
        self.assertEqual(model.model_name, "embed-model")
        self.assertEqual(model._embedding_endpoint(), "https://embed.example.com/v1/embeddings")

        settings_without_key = SimpleNamespace(
            openai_embedding_api_key="",
            openai_embedding_base_url="",
            openai_embedding_model="",
            openai_embedding_fallback_model="",
        )
        with patch("app.utils.api_key_manager.get_settings", return_value=settings_without_key), self.assertRaises(RuntimeError):
            api_key_manager.OpenAIEmbeddings()

        with patch("app.utils.api_key_manager.OpenAIEmbeddings", return_value="embedding-model") as model_cls:
            self.assertEqual(api_key_manager.create_embedding_model(api_key="k", model_name="m", base_url="u"), "embedding-model")
        self.assertEqual(model_cls.call_args.kwargs, {"api_key": "k", "model_name": "m", "base_url": "u"})

        with patch("app.utils.api_key_manager.get_settings", return_value=self.settings), patch(
            "app.utils.api_key_manager.create_embedding_model",
            return_value="primary",
        ):
            self.assertEqual(api_key_manager.get_embedding_model(), "primary")

        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(openai_embedding_api_key="", openai_embedding_fallback_model="", openai_embedding_base_url=""),
        ):
            self.assertIsNone(api_key_manager.get_embedding_model())

        with patch("app.utils.api_key_manager.get_settings", return_value=self.settings), patch(
            "app.utils.api_key_manager.create_embedding_model",
            return_value="fallback",
        ) as create_model:
            self.assertEqual(api_key_manager.get_fallback_embedding_model(), "fallback")
        self.assertEqual(
            create_model.call_args.kwargs,
            {"model_name": "fallback-model", "base_url": "https://embed.example.com/v1/"},
        )

        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(openai_embedding_api_key="embed-key", openai_embedding_fallback_model="", openai_embedding_base_url=""),
        ):
            self.assertIsNone(api_key_manager.get_fallback_embedding_model())

    def test_post_embeddings_success_and_async_wrappers(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=self.settings), patch(
            "app.utils.api_key_manager.OpenAI",
            return_value="openai-client",
        ):
            model = api_key_manager.OpenAIEmbeddings()

        documents_response = FakeResponse(
            payload={
                "data": [
                    {"index": 1, "embedding": [3.0, 4.0]},
                    {"index": 0, "embedding": [1.0, 2.0]},
                ]
            },
            text='{"data": "..."}',
        )
        query_response = FakeResponse(
            payload={"data": [{"index": 0, "embedding": [9.0, 8.0]}]},
            text='{"data": "..."}',
        )
        with patch(
            "app.utils.api_key_manager.requests.post",
            side_effect=[documents_response, query_response],
        ) as post:
            documents = model.embed_documents(["a", "b"])
            query = model.embed_query("hello")

        self.assertEqual(documents, [[1.0, 2.0], [3.0, 4.0]])
        self.assertEqual(query, [9.0, 8.0])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer embed-key")

        with patch.object(model, "embed_query", return_value=[9.0]), patch.object(
            model,
            "embed_documents",
            return_value=[[8.0]],
        ):
            import asyncio

            self.assertEqual(asyncio.run(model.aembed_query("q")), [9.0])
            self.assertEqual(asyncio.run(model.aembed_documents(["d"])), [[8.0]])

    def test_post_embeddings_error_paths(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=self.settings), patch(
            "app.utils.api_key_manager.OpenAI",
            return_value="openai-client",
        ):
            model = api_key_manager.OpenAIEmbeddings()

        with patch(
            "app.utils.api_key_manager.requests.post",
            side_effect=requests.RequestException("network down"),
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                model.embed_query("hello")
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.code, "EMBEDDING_UPSTREAM_FAILED")

        cases = [
            (
                FakeResponse(status_code=503, text="bad gateway", json_error=ValueError("no json")),
                "EMBEDDING_RESPONSE_INVALID",
            ),
            (
                FakeResponse(status_code=400, payload={"error": {"code": "123", "message": "bad request"}}, text="{}"),
                "EMBEDDING_UPSTREAM_FAILED",
            ),
            (
                FakeResponse(status_code=502, payload={"message": "gateway"}, text="{}"),
                "EMBEDDING_UPSTREAM_FAILED",
            ),
            (
                FakeResponse(status_code=200, payload=["not-a-dict"], text="[]"),
                "EMBEDDING_RESPONSE_INVALID",
            ),
            (
                FakeResponse(status_code=200, payload={"data": []}, text="{}"),
                "EMBEDDING_RESPONSE_INVALID",
            ),
            (
                FakeResponse(status_code=200, payload={"data": ["bad-item"]}, text="{}"),
                "EMBEDDING_RESPONSE_INVALID",
            ),
            (
                FakeResponse(status_code=200, payload={"data": [{"index": 0, "embedding": []}]}, text="{}"),
                "EMBEDDING_RESPONSE_INVALID",
            ),
            (
                FakeResponse(status_code=200, payload={"data": [{"index": 0, "embedding": [1.0]}]}, text="{}"),
                "EMBEDDING_RESPONSE_INVALID",
            ),
        ]

        for response, expected_code in cases:
            with self.subTest(expected_code=expected_code, payload=response._payload):
                with patch("app.utils.api_key_manager.requests.post", return_value=response):
                    with self.assertRaises(EmbeddingProviderError) as ctx:
                        model.embed_documents(["only", "two"])
                self.assertEqual(ctx.exception.code, expected_code)


class StructuredModelFactoryTests(ApiKeyManagerBase):
    def test_structured_model_factories(self):
        api_key_manager._keys = ["key-1", "key-2"]
        api_key_manager._index = 1

        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(google_ai_model="flash-model"),
        ), patch(
            "app.utils.api_key_manager.ChatGoogleGenerativeAI",
            side_effect=lambda **kwargs: FakeChatModel(**kwargs),
        ):
            query_model = api_key_manager.get_query_entity_extraction_model()
            graph_model = api_key_manager.get_graph_extraction_model()
            answer_model = api_key_manager.get_answer_generation_model({"type": "object"})
            explicit_answer_model = api_key_manager.get_answer_generation_model(
                {"type": "object"},
                options={"temperature": 0.2, "thinking_budget": 64},
                api_key="explicit-key",
            )

        self.assertEqual(query_model["kwargs"]["api_key"], "key-1")
        self.assertEqual(graph_model["kwargs"]["api_key"], "key-2")
        self.assertEqual(answer_model["kwargs"]["temperature"], 0.7)
        self.assertEqual(answer_model["kwargs"]["model_kwargs"]["thinking_config"]["thinking_budget"], 0)
        self.assertEqual(explicit_answer_model["kwargs"]["api_key"], "explicit-key")
        self.assertEqual(explicit_answer_model["kwargs"]["temperature"], 0.2)
        self.assertEqual(
            explicit_answer_model["kwargs"]["model_kwargs"]["thinking_config"]["thinking_budget"],
            64,
        )

        api_key_manager._keys = []
        api_key_manager._index = 0
        with patch(
            "app.utils.api_key_manager.get_settings",
            return_value=SimpleNamespace(google_api_key_list="", google_ai_model="flash-model"),
        ):
            self.assertIsNone(api_key_manager.get_query_entity_extraction_model())
            self.assertIsNone(api_key_manager.get_graph_extraction_model())
            self.assertIsNone(api_key_manager.get_answer_generation_model({"type": "object"}))

        api_key_manager._keys = ["key-1"]
        api_key_manager._index = 1
        self.assertIsNone(api_key_manager.get_graph_extraction_model())
        self.assertIsNone(api_key_manager.get_answer_generation_model({"type": "object"}))


class RetryWrapperTests(ApiKeyManagerBase, unittest.IsolatedAsyncioTestCase):
    async def test_async_retry_success_and_http_exception_path(self):
        api_key_manager._keys = ["key-1", "key-2"]
        api_key_manager._index = 0
        calls = []

        async def succeed_on_second(api_key, value):
            calls.append(api_key)
            if api_key == "key-1":
                raise RuntimeError("first failed")
            return value

        with patch("app.utils.api_key_manager.asyncio.sleep", AsyncMock()) as sleeper:
            result = await api_key_manager.with_gemini_retry_async("op", succeed_on_second, 7, retry_delay=0.1)
        self.assertEqual(result, 7)
        self.assertEqual(calls, ["key-1", "key-2"])
        sleeper.assert_called_once()

        api_key_manager._keys = ["key-1"]
        api_key_manager._index = 0
        with self.assertRaises(HTTPException) as ctx:
            await api_key_manager.with_gemini_retry_async(
                "op",
                succeed_on_second,
                7,
                retry_delay=0,
                error_type=HTTPException,
                max_retries=1,
            )
        self.assertEqual(ctx.exception.status_code, 500)


class RetryWrapperSyncTests(ApiKeyManagerBase):
    def test_sync_retry_success_sleep_and_http_exception_path(self):
        api_key_manager._keys = ["key-1", "key-2"]
        api_key_manager._index = 0
        calls = []

        def succeed_on_second(api_key, value):
            calls.append(api_key)
            if api_key == "key-1":
                raise RuntimeError("first failed")
            return value

        with patch("app.utils.api_key_manager.time.sleep") as sleeper:
            result = api_key_manager.with_gemini_retry_sync("op", succeed_on_second, 9, retry_delay=0.1)
        self.assertEqual(result, 9)
        self.assertEqual(calls, ["key-1", "key-2"])
        sleeper.assert_called_once()

        api_key_manager._keys = ["key-1"]
        api_key_manager._index = 0
        with self.assertRaises(HTTPException) as ctx:
            api_key_manager.with_gemini_retry_sync(
                "op",
                succeed_on_second,
                9,
                retry_delay=0,
                error_type=HTTPException,
                max_retries=1,
            )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_sync_retry_breaks_when_no_current_key(self):
        def should_not_run(api_key):
            raise AssertionError("should not be called")

        with patch("app.utils.api_key_manager.reset_key_index"), patch(
            "app.utils.api_key_manager.get_keys_count", return_value=1
        ), patch(
            "app.utils.api_key_manager.get_current_api_key",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                api_key_manager.with_gemini_retry_sync("op", should_not_run, retry_delay=0)
        self.assertIn("attempted 0/1 configured keys", str(ctx.exception))
