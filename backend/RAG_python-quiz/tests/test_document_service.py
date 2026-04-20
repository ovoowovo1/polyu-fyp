import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import document_service
from app.utils.ingest_errors import EmbeddingProviderError


def make_retryable_error(raw_preview="upstream"):
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
        raw_preview=raw_preview,
    )


def make_settings(
    *,
    fallback_model="google/gemini-embedding-2-preview",
    fallback_column="embedding_v2",
    base_url="https://openrouter.ai/api/v1",
):
    return SimpleNamespace(
        openai_embedding_fallback_model=fallback_model,
        openai_embedding_fallback_column=fallback_column,
        openai_embedding_base_url=base_url,
    )


class SplittingModel:
    model_name = "google/gemini-embedding-001"
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self):
        self.calls = []

    async def aembed_documents(self, texts):
        self.calls.append(list(texts))
        if len(texts) > 1:
            raise make_retryable_error()
        token = texts[0].split("-")[-1]
        return [[float(token)]]


class SingleFailureModel:
    model_name = "google/gemini-embedding-001"
    base_url = "https://openrouter.ai/api/v1"

    async def aembed_documents(self, texts):
        if len(texts) > 1:
            raise make_retryable_error()
        if texts[0] == "bad":
            raise make_retryable_error(raw_preview="raw bad chunk response")
        return [[1.0]]


class DocumentServiceEmbeddingTests(unittest.IsolatedAsyncioTestCase):
    async def test_adaptive_batch_splitting_preserves_chunk_order(self):
        chunks = [
            {"pageContent": f"chunk-{index}", "metadata": {"pageNumber": 1}}
            for index in range(4)
        ]
        model = SplittingModel()

        with patch("app.services.document_service.create_embedding_model", return_value=model), patch(
            "app.services.document_service.asyncio.sleep",
            return_value=None,
        ):
            vectors = await document_service._embed_chunks_with_retry(chunks)

        self.assertEqual(vectors, [[0.0], [1.0], [2.0], [3.0]])
        self.assertGreaterEqual(len(model.calls), 7)

    async def test_single_chunk_terminal_failure_preserves_structured_error(self):
        chunks = [
            {"pageContent": "good", "metadata": {"pageNumber": 1}},
            {"pageContent": "bad", "metadata": {"pageNumber": 1}},
        ]
        model = SingleFailureModel()

        with patch("app.services.document_service.create_embedding_model", return_value=model), patch(
            "app.services.document_service.asyncio.sleep",
            return_value=None,
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                await document_service._embed_chunks_with_retry(chunks)

        error = ctx.exception
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertEqual(error.raw_preview, "raw bad chunk response")

    async def test_embed_chunks_for_storage_keeps_primary_when_standby_fails(self):
        chunks = [
            {"pageContent": "chunk-1", "metadata": {"pageNumber": 1}},
            {"pageContent": "chunk-2", "metadata": {"pageNumber": 1}},
        ]
        primary_model = object()
        fallback_model = object()

        with patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(),
        ), patch(
            "app.services.document_service.create_embedding_model",
            side_effect=[primary_model, fallback_model],
        ) as create_model, patch(
            "app.services.document_service.embed_texts_with_retry",
            side_effect=[
                [[1.0], [2.0]],
                make_retryable_error(raw_preview="fallback raw response"),
            ],
        ):
            primary_vectors, fallback_vectors = await document_service._embed_chunks_for_storage(chunks)

        self.assertEqual(primary_vectors, [[1.0], [2.0]])
        self.assertIsNone(fallback_vectors)
        self.assertEqual(create_model.call_count, 2)

    async def test_embed_chunks_for_storage_raises_when_primary_fails(self):
        chunks = [{"pageContent": "chunk-1", "metadata": {"pageNumber": 1}}]

        with patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(),
        ), patch(
            "app.services.document_service.create_embedding_model",
            return_value=object(),
        ) as create_model, patch(
            "app.services.document_service.embed_texts_with_retry",
            side_effect=make_retryable_error(raw_preview="primary raw response"),
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                await document_service._embed_chunks_for_storage(chunks)

        self.assertEqual(create_model.call_count, 1)
        self.assertEqual(ctx.exception.raw_preview, "primary raw response")
