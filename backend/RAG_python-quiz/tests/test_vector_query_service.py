from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.services import vector_query_service
from app.utils.ingest_errors import EmbeddingProviderError


def make_settings():
    return SimpleNamespace(
        embedding_active_column="embedding",
        embedding_fallback_column="embedding_v2",
    )


def make_retryable_error():
    return EmbeddingProviderError(
        code="EMBEDDING_UPSTREAM_FAILED",
        message="Embedding upstream failed: No successful provider responses.",
        retryable=True,
        provider="openrouter",
        model="google/gemini-embedding-001",
        base_url="https://openrouter.ai/api/v1",
        http_status=200,
        upstream_code=404,
        upstream_message="No successful provider responses.",
        raw_preview='{"error":{"message":"No successful provider responses.","code":404}}',
    )


def make_no_endpoints_error():
    return EmbeddingProviderError(
        code="EMBEDDING_UPSTREAM_FAILED",
        message="Embedding upstream failed: No endpoints found for google/gemini-embedding-001.",
        retryable=True,
        provider="openrouter",
        model="google/gemini-embedding-001",
        base_url="https://openrouter.ai/api/v1",
        http_status=200,
        upstream_code=404,
        upstream_message="No endpoints found for google/gemini-embedding-001.",
        raw_preview='{"error":{"message":"No endpoints found for google/gemini-embedding-001.","code":404}}',
    )


class SuccessfulQueryModel:
    def __init__(self, model_name, vector):
        self.model_name = model_name
        self.vector = vector
        self.calls = []

    async def aembed_query(self, text):
        self.calls.append(text)
        return self.vector


class RetryableFailingQueryModel:
    model_name = "google/gemini-embedding-001"

    async def aembed_query(self, text):
        raise make_retryable_error()


class ValueErrorQueryModel:
    model_name = "google/gemini-embedding-001"

    async def aembed_query(self, text):
        raise ValueError("bad input")


class VectorQueryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_vector_context_requires_primary_embedding_model(self):
        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertIn("Embedding API Key not configured", str(ctx.exception))

    async def test_retrieve_vector_context_uses_primary_model_by_default(self):
        primary_model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])

        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=primary_model,
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
        ) as get_fallback_model, patch(
            "app.services.vector_query_service.pg_service.retrieve_graph_context",
            return_value=[{"chunkId": "chunk-1"}],
        ) as retrieve_graph_context:
            rows, mode = await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(mode, "primary")
        self.assertEqual(rows, [{"chunkId": "chunk-1"}])
        retrieve_graph_context.assert_called_once_with(
            [0.1, 0.2],
            20,
            ["file-1"],
            embedding_column="embedding",
        )
        get_fallback_model.assert_not_called()

    async def test_retrieve_vector_context_falls_back_on_retryable_provider_error(self):
        fallback_model = SuccessfulQueryModel("google/gemini-embedding-2-preview", [0.3, 0.4])

        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=RetryableFailingQueryModel(),
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
            return_value=fallback_model,
        ) as get_fallback_model, patch(
            "app.services.vector_query_service.pg_service.retrieve_graph_context",
            return_value=[{"chunkId": "chunk-2"}],
        ) as retrieve_graph_context:
            rows, mode = await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(mode, "fallback")
        self.assertEqual(rows, [{"chunkId": "chunk-2"}])
        retrieve_graph_context.assert_called_once_with(
            [0.3, 0.4],
            20,
            ["file-1"],
            embedding_column="embedding_v2",
        )
        get_fallback_model.assert_called_once()

    async def test_retrieve_vector_context_re_raises_when_fallback_model_missing(self):
        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=RetryableFailingQueryModel(),
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
            return_value=None,
        ):
            with self.assertRaises(EmbeddingProviderError):
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

    async def test_retrieve_vector_context_falls_back_on_no_endpoints_found_error(self):
        fallback_model = SuccessfulQueryModel("google/gemini-embedding-2-preview", [0.5, 0.6])

        class NoEndpointsFailingQueryModel:
            model_name = "google/gemini-embedding-001"

            async def aembed_query(self, text):
                raise make_no_endpoints_error()

        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=NoEndpointsFailingQueryModel(),
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
            return_value=fallback_model,
        ) as get_fallback_model, patch(
            "app.services.vector_query_service.pg_service.retrieve_graph_context",
            return_value=[{"chunkId": "chunk-3"}],
        ) as retrieve_graph_context:
            rows, mode = await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(mode, "fallback")
        self.assertEqual(rows, [{"chunkId": "chunk-3"}])
        retrieve_graph_context.assert_called_once_with(
            [0.5, 0.6],
            20,
            ["file-1"],
            embedding_column="embedding_v2",
        )
        get_fallback_model.assert_called_once()

    async def test_retrieve_vector_context_does_not_fallback_on_empty_primary_results(self):
        primary_model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])

        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=primary_model,
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
        ) as get_fallback_model, patch(
            "app.services.vector_query_service.pg_service.retrieve_graph_context",
            return_value=[],
        ) as retrieve_graph_context:
            rows, mode = await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(mode, "primary")
        self.assertEqual(rows, [])
        retrieve_graph_context.assert_called_once()
        get_fallback_model.assert_not_called()

    async def test_retrieve_vector_context_does_not_fallback_on_local_error(self):
        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=ValueErrorQueryModel(),
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
        ) as get_fallback_model:
            with self.assertRaises(ValueError):
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        get_fallback_model.assert_not_called()

    async def test_retrieve_vector_context_re_raises_fallback_error(self):
        fallback_error = make_retryable_error()

        class RetryableFallbackModel:
            model_name = "google/gemini-embedding-2-preview"

            async def aembed_query(self, text):
                raise fallback_error

        with patch("app.services.vector_query_service.get_settings", return_value=make_settings()), patch(
            "app.services.vector_query_service.get_embedding_model",
            return_value=RetryableFailingQueryModel(),
        ), patch(
            "app.services.vector_query_service.get_fallback_embedding_model",
            return_value=RetryableFallbackModel(),
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertIs(ctx.exception, fallback_error)
