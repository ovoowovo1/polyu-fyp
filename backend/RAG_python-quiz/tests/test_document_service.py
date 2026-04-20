import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
    async def test_small_helper_functions_cover_pdf_detection_error_wrapping_and_chunk_assembly(self):
        self.assertTrue(document_service._is_pdf_upload("file.pdf", "application/octet-stream"))
        self.assertFalse(document_service._is_pdf_upload("file.txt", "text/plain"))

        wrapped = document_service._coerce_embedding_error(
            RuntimeError("boom"),
            model_name="model",
            base_url="https://example.com",
        )
        self.assertFalse(wrapped.retryable)
        self.assertIs(
            document_service._coerce_embedding_error(
                wrapped,
                model_name="model",
                base_url="https://example.com",
            ),
            wrapped,
        )

        rows = document_service._assemble_chunks_for_db(
            [{"pageContent": "chunk", "metadata": {"pageNumber": 1}}],
            [[1.0]],
            [[2.0]],
        )
        self.assertEqual(rows[0]["embedding"], [1.0])
        self.assertEqual(rows[0]["embedding_v2"], [2.0])

        self.assertEqual(await document_service.embed_texts_with_retry([]), [])

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

    async def test_embed_batch_and_storage_cover_remaining_edge_cases(self):
        class NonRetryableModel:
            model_name = "model"
            base_url = "https://example.com"

            async def aembed_documents(self, texts):
                raise EmbeddingProviderError(
                    code="EMBEDDING_UPSTREAM_FAILED",
                    message="fatal",
                    retryable=False,
                    provider="openrouter",
                    model="model",
                    base_url="https://example.com",
                )

        with self.assertRaises(EmbeddingProviderError):
            await document_service._embed_batch_with_adaptive_retry(["text"], NonRetryableModel(), batch_label="1")

        original_attempts = document_service.EMBED_RETRY_ATTEMPTS
        document_service.EMBED_RETRY_ATTEMPTS = 0
        try:
            with self.assertRaises(RuntimeError):
                await document_service._embed_batch_with_adaptive_retry(["text"], NonRetryableModel(), batch_label="1")
        finally:
            document_service.EMBED_RETRY_ATTEMPTS = original_attempts

        chunks = [{"pageContent": "chunk-1", "metadata": {"pageNumber": 1}}]
        with patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(fallback_model="", fallback_column="embedding"),
        ), patch(
            "app.services.document_service.create_embedding_model",
            return_value=object(),
        ), patch(
            "app.services.document_service.embed_texts_with_retry",
            return_value=[[1.0]],
        ):
            primary_only = await document_service._embed_chunks_for_storage(chunks)
        self.assertEqual(primary_only, ([[1.0]], None))

        primary_model = object()
        fallback_model = object()
        with patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(),
        ), patch(
            "app.services.document_service.create_embedding_model",
            side_effect=[primary_model, fallback_model],
        ), patch(
            "app.services.document_service.embed_texts_with_retry",
            side_effect=[[[1.0]], [[2.0]]],
        ):
            vectors = await document_service._embed_chunks_for_storage(chunks)
        self.assertEqual(vectors, ([[1.0]], [[2.0]]))

    async def test_ingest_document_covers_validation_duplicate_and_failure_paths(self):
        with self.assertRaises(document_service.DocumentIngestError):
            await document_service.ingest_document(
                filename="notes.txt",
                content=b"text",
                size=4,
                mimetype="text/plain",
            )

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value={"id": "doc-1"}):
            duplicate = await document_service.ingest_document(
                filename="notes.pdf",
                content=b"pdf",
                size=3,
                mimetype="application/pdf",
            )
        self.assertFalse(duplicate["isNew"])

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(side_effect=RuntimeError("extract failed")),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(return_value=["short", "   "]),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(return_value=["This page contains enough text to be chunked."]),
        ), patch(
            "app.services.document_service._embed_chunks_for_storage",
            AsyncMock(side_effect=make_retryable_error("embed failed")),
        ):
            with self.assertRaises(EmbeddingProviderError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(return_value=["This page contains enough text to be chunked."]),
        ), patch(
            "app.services.document_service._embed_chunks_for_storage",
            AsyncMock(side_effect=RuntimeError("embed failed")),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(return_value=["This page contains enough text to be chunked."]),
        ), patch(
            "app.services.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(fallback_column="embedding_v2"),
        ), patch(
            "app.services.document_service.pg_service.create_graph_from_document",
            side_effect=RuntimeError("db failed"),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

    async def test_ingest_document_and_website_success_paths(self):
        with patch("app.services.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.document_service.extract_text_by_page",
            AsyncMock(return_value=["This page contains enough text to be chunked."]),
        ), patch(
            "app.services.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], [[2.0]])),
        ), patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(fallback_column="embedding_v2"),
        ), patch(
            "app.services.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "doc-1"},
        ):
            result = await document_service.ingest_document(
                filename="notes.pdf",
                content=b"pdf",
                size=3,
                mimetype="application/pdf",
                class_id="class-1",
            )
        self.assertTrue(result["isNew"])
        self.assertEqual(result["fileId"], "doc-1")

        with patch("app.services.document_service.load_markdown", AsyncMock(return_value=[])):
            with self.assertRaises(RuntimeError):
                await document_service.ingest_website(url="https://example.com")

        with patch(
            "app.services.document_service.load_markdown",
            AsyncMock(return_value=[SimpleNamespace(page_content="   "), SimpleNamespace(page_content="")]),
        ):
            with self.assertRaises(RuntimeError):
                await document_service.ingest_website(url="https://example.com")

        docs = [SimpleNamespace(page_content=""), SimpleNamespace(page_content="Actual website content")]
        with patch("app.services.document_service.load_markdown", AsyncMock(return_value=docs)), patch(
            "app.services.document_service.pg_service.find_document_by_hash",
            return_value={"id": "doc-1"},
        ):
            duplicate = await document_service.ingest_website(url="https://example.com")
        self.assertFalse(duplicate["isNew"])

        progress = AsyncMock()
        with patch("app.services.document_service.load_markdown", AsyncMock(return_value=[SimpleNamespace(page_content="Actual website content")])), patch(
            "app.services.document_service.pg_service.find_document_by_hash",
            return_value=None,
        ), patch(
            "app.services.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.document_service.get_settings",
            return_value=make_settings(fallback_column="embedding"),
        ), patch(
            "app.services.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "doc-2"},
        ), patch(
            "app.services.document_service.publish_progress",
            progress,
        ):
            result = await document_service.ingest_website(
                url="https://example.com",
                client_id="client-1",
                class_id="class-1",
            )

        self.assertEqual(result["fileId"], "doc-2")
        self.assertEqual(progress.await_count, 3)
