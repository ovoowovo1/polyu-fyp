from contextlib import contextmanager
from unittest.mock import patch
import unittest

from app.services.rag import vector_query_service
from app.utils.ingest_errors import EmbeddingProviderError
from tests.support import make_embedding_error as make_retryable_error
from tests.support import make_embedding_settings

EMBEDDING_SETTINGS = make_embedding_settings(embedding_active_column="embedding")
UNSET = object()


def make_no_endpoints_error():
    message = "No endpoints found for google/gemini-embedding-001."
    return make_retryable_error(
        upstream_message=message,
        raw_preview=f'{{"error":{{"message":"{message}","code":404}}}}',
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


@contextmanager
def patched_vector_dependencies(primary_model, *, fallback_model=UNSET, rows=UNSET):
    fallback_patch = patch("app.services.rag.vector_query_service.get_fallback_embedding_model")
    if fallback_model is not UNSET:
        fallback_patch = patch(
            "app.services.rag.vector_query_service.get_fallback_embedding_model",
            return_value=fallback_model,
        )

    rows = rows if rows is not UNSET else [{"chunkId": "chunk"}]
    with patch(
        "app.services.rag.vector_query_service.get_settings",
        return_value=EMBEDDING_SETTINGS,
    ), patch(
        "app.services.rag.vector_query_service.get_embedding_model",
        return_value=primary_model,
    ), fallback_patch as get_fallback_model, patch(
        "app.services.rag.vector_query_service.pg_service.retrieve_graph_context",
        return_value=rows,
    ) as retrieve_graph_context:
        yield retrieve_graph_context, get_fallback_model


class VectorQueryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_vector_context_requires_primary_embedding_model(self):
        with patched_vector_dependencies(primary_model=None):
            with self.assertRaises(RuntimeError) as ctx:
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertIn("Embedding API Key not configured", str(ctx.exception))

    async def test_retrieve_vector_context_uses_primary_model_by_default(self):
        primary_model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])

        with patched_vector_dependencies(primary_model, rows=[{"chunkId": "chunk-1"}]) as (
            retrieve_graph_context,
            get_fallback_model,
        ):
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

        with patched_vector_dependencies(
            RetryableFailingQueryModel(),
            fallback_model=fallback_model,
            rows=[{"chunkId": "chunk-2"}],
        ) as (retrieve_graph_context, get_fallback_model):
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
        with patched_vector_dependencies(RetryableFailingQueryModel(), fallback_model=None):
            with self.assertRaises(EmbeddingProviderError):
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

    async def test_retrieve_vector_context_falls_back_on_no_endpoints_found_error(self):
        fallback_model = SuccessfulQueryModel("google/gemini-embedding-2-preview", [0.5, 0.6])

        class NoEndpointsFailingQueryModel:
            model_name = "google/gemini-embedding-001"

            async def aembed_query(self, text):
                raise make_no_endpoints_error()

        with patched_vector_dependencies(
            NoEndpointsFailingQueryModel(),
            fallback_model=fallback_model,
            rows=[{"chunkId": "chunk-3"}],
        ) as (retrieve_graph_context, get_fallback_model):
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

        with patched_vector_dependencies(primary_model, rows=[]) as (
            retrieve_graph_context,
            get_fallback_model,
        ):
            rows, mode = await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(mode, "primary")
        self.assertEqual(rows, [])
        retrieve_graph_context.assert_called_once()
        get_fallback_model.assert_not_called()

    async def test_retrieve_vector_context_does_not_fallback_on_local_error(self):
        with patched_vector_dependencies(ValueErrorQueryModel()) as (_, get_fallback_model):
            with self.assertRaises(ValueError):
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        get_fallback_model.assert_not_called()

    async def test_retrieve_vector_context_re_raises_fallback_error(self):
        fallback_error = make_retryable_error()

        class RetryableFallbackModel:
            model_name = "google/gemini-embedding-2-preview"

            async def aembed_query(self, text):
                raise fallback_error

        with patched_vector_dependencies(
            RetryableFailingQueryModel(),
            fallback_model=RetryableFallbackModel(),
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                await vector_query_service.retrieve_vector_context("hello", ["file-1"])

        self.assertIs(ctx.exception, fallback_error)
