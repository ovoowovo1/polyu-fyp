import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.documents import document_service, ingestion_steps
from app.utils.ingest_errors import EmbeddingProviderError
from tests.support import make_embedding_error as make_retryable_error
from tests.support import make_embedding_settings

STANDBY_SETTINGS = make_embedding_settings(embedding_fallback_model="google/gemini-embedding-2-preview")
PRIMARY_ONLY_SETTINGS = make_embedding_settings(embedding_fallback_model="", embedding_fallback_column="embedding")
FALLBACK_V2_SETTINGS = make_embedding_settings(embedding_fallback_column="embedding_v2")
FALLBACK_LEGACY_SETTINGS = make_embedding_settings(embedding_fallback_column="embedding")


def markdown_doc(page_content):
    return SimpleNamespace(page_content=page_content)


def pdf_pages(*texts):
    return [
        {"pageNumber": index, "text": text, "images": []}
        for index, text in enumerate(texts, start=1)
    ]


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
        self.assertTrue(document_service._is_image_upload("figure.png", "application/octet-stream"))
        self.assertTrue(document_service._is_supported_upload("figure.jpg", "application/octet-stream"))
        self.assertFalse(document_service._is_supported_upload("notes.txt", "text/plain"))
        with self.assertRaises(document_service.DocumentIngestError):
            ingestion_steps.validate_pdf_upload("notes.txt", "text/plain", lambda *_args: False)

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
        self.assertEqual(
            await document_service.embedding_pipeline.embed_texts_with_retry(
                [],
                embeddings_model=object(),
                create_embedding_model=lambda: object(),
                initial_batch_size=1,
                embed_batch=AsyncMock(),
                logger=SimpleNamespace(),
            ),
            [],
        )
        self.assertEqual(
            ingestion_steps.build_pdf_chunks(
                "legacy.pdf",
                ["A sufficiently long legacy text page."],
                SimpleNamespace(split_text=lambda text: [text]),
            )[0]["metadata"]["pageNumber"],
            1,
        )
        self.assertEqual(
            document_service._assemble_chunks_for_db(
                [{"pageContent": "Image", "metadata": {}, "imageData": b"x", "imageMimetype": "image/png"}],
                [[1.0]],
            )[0]["image_data"],
            b"x",
        )

    def test_pdf_chunk_builder_keeps_text_and_embedded_image_chunks(self):
        splitter = SimpleNamespace(split_text=lambda text: [text])
        pages = [
            {
                "pageNumber": 2,
                "text": "A sufficiently long page text for extraction.",
                "images": [
                    {"data": b"image", "mimetype": "image/png", "imageIndex": 1},
                ],
            }
        ]

        chunks = ingestion_steps.build_pdf_chunks("lesson.pdf", pages, splitter)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["metadata"]["pageNumber"], 2)
        self.assertEqual(chunks[1]["metadata"]["imageIndex"], 1)
        self.assertEqual(chunks[1]["imageData"], b"image")
        self.assertEqual(chunks[1]["embeddingInput"]["content"][0]["type"], "image_url")

    def test_pdf_chunk_builder_accepts_image_only_and_rejects_empty_pdf(self):
        splitter = SimpleNamespace(split_text=lambda text: [text])
        image_only = [{
            "pageNumber": 1,
            "text": "",
            "images": [{"data": b"image", "mimetype": "image/jpeg", "imageIndex": 1}],
        }]
        self.assertEqual(
            ingestion_steps.build_pdf_chunks("scan.pdf", image_only, splitter)[0]["imageMimetype"],
            "image/jpeg",
        )

        with self.assertRaises(document_service.DocumentIngestError) as error:
            ingestion_steps.build_pdf_chunks(
                "empty.pdf",
                [{"pageNumber": 1, "text": "", "images": []}],
                splitter,
            )
        self.assertEqual(error.exception.code, "EMPTY_DOCUMENT")

    async def test_adaptive_batch_splitting_preserves_chunk_order(self):
        chunks = [
            {"pageContent": f"chunk-{index}", "metadata": {"pageNumber": 1}}
            for index in range(4)
        ]
        model = SplittingModel()

        with patch("app.services.documents.document_service.create_embedding_model", return_value=model), patch(
            "app.services.documents.document_service.asyncio.sleep",
            return_value=None,
        ):
            vectors = await document_service.embed_texts_with_retry([chunk["pageContent"] for chunk in chunks])

        self.assertEqual(vectors, [[0.0], [1.0], [2.0], [3.0]])
        self.assertGreaterEqual(len(model.calls), 7)

    async def test_mixed_embedding_inputs_limit_each_request_to_six_images(self):
        inputs = [
            {"content": bytes([index]), "mime_type": "image/png"}
            for index in range(7)
        ]
        calls = []

        async def fake_embed(batch, **_kwargs):
            calls.append(list(batch))
            return [[float(index)] for index, _ in enumerate(batch)]

        with patch(
            "app.services.documents.document_service.embedding_pipeline.embed_texts_with_retry",
            side_effect=fake_embed,
        ):
            vectors = await document_service.embed_texts_with_retry(inputs)

        self.assertEqual([len(batch) for batch in calls], [6, 1])
        self.assertEqual(len(vectors), 7)

    async def test_single_chunk_terminal_failure_preserves_structured_error(self):
        chunks = [
            {"pageContent": "good", "metadata": {"pageNumber": 1}},
            {"pageContent": "bad", "metadata": {"pageNumber": 1}},
        ]
        model = SingleFailureModel()

        with patch("app.services.documents.document_service.create_embedding_model", return_value=model), patch(
            "app.services.documents.document_service.asyncio.sleep",
            return_value=None,
        ):
            with self.assertRaises(EmbeddingProviderError) as ctx:
                await document_service.embed_texts_with_retry([chunk["pageContent"] for chunk in chunks])

        error = ctx.exception
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertEqual(error.raw_preview, "raw bad chunk response")

    async def test_embed_chunks_for_storage_keeps_primary_when_standby_fails(self):
        chunks = [
            {"pageContent": "chunk-1", "metadata": {"pageNumber": 1}},
            {
                "pageContent": "Image source: figure.png",
                "metadata": {"pageNumber": 1},
                "embeddingInput": {"content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1n"}}]},
            },
        ]
        primary_model = object()
        fallback_model = object()

        with patch(
            "app.services.documents.document_service.get_settings",
            return_value=STANDBY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.create_embedding_model",
            side_effect=[primary_model, fallback_model],
        ) as create_model, patch(
            "app.services.documents.document_service.embed_texts_with_retry",
            side_effect=[
                [[1.0], [2.0]],
                make_retryable_error(raw_preview="fallback raw response"),
            ],
        ) as embed_texts:
            primary_vectors, fallback_vectors = await document_service._embed_chunks_for_storage(chunks)

        self.assertEqual(primary_vectors, [[1.0], [2.0]])
        self.assertIsNone(fallback_vectors)
        self.assertEqual(create_model.call_count, 2)
        self.assertEqual(embed_texts.await_args_list[0].args[0][1], chunks[1]["embeddingInput"])

    async def test_embed_chunks_for_storage_raises_when_primary_fails(self):
        chunks = [{"pageContent": "chunk-1", "metadata": {"pageNumber": 1}}]

        with patch(
            "app.services.documents.document_service.get_settings",
            return_value=STANDBY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.create_embedding_model",
            return_value=object(),
        ) as create_model, patch(
            "app.services.documents.document_service.embed_texts_with_retry",
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
            "app.services.documents.document_service.get_settings",
            return_value=PRIMARY_ONLY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.create_embedding_model",
            return_value=object(),
        ), patch(
            "app.services.documents.document_service.embed_texts_with_retry",
            return_value=[[1.0]],
        ):
            primary_only = await document_service._embed_chunks_for_storage(chunks)
        self.assertEqual(primary_only, ([[1.0]], None))

        primary_model = object()
        fallback_model = object()
        with patch(
            "app.services.documents.document_service.get_settings",
            return_value=STANDBY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.create_embedding_model",
            side_effect=[primary_model, fallback_model],
        ), patch(
            "app.services.documents.document_service.embed_texts_with_retry",
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

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value={"id": "doc-1"}) as find_duplicate:
            duplicate = await document_service.ingest_document(
                filename="notes.pdf",
                content=b"pdf",
                size=3,
                mimetype="application/pdf",
                class_id="class-1",
            )
        self.assertFalse(duplicate["isNew"])
        self.assertEqual(find_duplicate.call_args.args[1], "class-1")

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(side_effect=RuntimeError("extract failed")),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("short", "   ")),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("This page contains enough text to be chunked.")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(side_effect=make_retryable_error("embed failed")),
        ):
            with self.assertRaises(EmbeddingProviderError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("This page contains enough text to be chunked.")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(side_effect=RuntimeError("embed failed")),
        ):
            with self.assertRaises(document_service.DocumentIngestError):
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("This page contains enough text to be chunked.")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_V2_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            side_effect=type("StorageFailure", (RuntimeError,), {"stage": "chunks"})("db failed"),
        ), patch("app.services.documents.document_service.logger") as logger:
            with self.assertRaises(document_service.DocumentIngestError) as error:
                await document_service.ingest_document(
                    filename="notes.pdf",
                    content=b"pdf",
                    size=3,
                    mimetype="application/pdf",
                )
        self.assertEqual(error.exception.details, "storage_stage=chunks")
        self.assertTrue(logger.error.call_args.kwargs["exc_info"])
        self.assertIn("storage_stage=%s", logger.error.call_args.args[0])

    async def test_ingest_document_and_website_success_paths(self):
        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("This page contains enough text to be chunked.")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], [[2.0]])),
        ), patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_V2_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
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

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(side_effect=AssertionError("PDF extraction should not run for images")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], [[2.0]])),
        ) as embed_chunks, patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_V2_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "image-1"},
        ) as create_graph:
            image_result = await document_service.ingest_document(
                filename="figure.png",
                content=b"img",
                size=3,
                mimetype="image/png",
                class_id="class-1",
            )

        self.assertEqual(image_result["fileId"], "image-1")
        image_chunks = embed_chunks.await_args.args[0]
        self.assertEqual(image_chunks[0]["pageContent"], "Image source: figure.png")
        self.assertEqual(image_chunks[0]["embeddingInput"]["content"][0]["type"], "image_url")
        self.assertEqual(create_graph.call_args.args[0]["mimetype"], "image/png")

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=[{
                "pageNumber": 3,
                "text": "",
                "images": [{"data": b"pdf-image", "mimetype": "image/png", "imageIndex": 1}],
            }]),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "pdf-image-1"},
        ) as create_pdf_graph:
            pdf_image_result = await document_service.ingest_document(
                filename="slides.pdf",
                content=b"pdf",
                size=3,
                mimetype="application/pdf",
                class_id="class-1",
            )

        self.assertEqual(pdf_image_result["fileId"], "pdf-image-1")
        pdf_chunks = create_pdf_graph.call_args.args[1]
        self.assertEqual(pdf_chunks[0]["image_data"], b"pdf-image")
        self.assertEqual(pdf_chunks[0]["metadata"]["pageNumber"], 3)

        with patch("app.services.documents.document_service.load_markdown", AsyncMock(return_value=[])):
            with self.assertRaises(RuntimeError):
                await document_service.ingest_website(url="https://example.com")

        with patch(
            "app.services.documents.document_service.load_markdown",
            AsyncMock(return_value=[markdown_doc("   "), markdown_doc("")]),
        ):
            with self.assertRaises(RuntimeError):
                await document_service.ingest_website(url="https://example.com")

        docs = [markdown_doc(""), markdown_doc("Actual website content")]
        with patch("app.services.documents.document_service.load_markdown", AsyncMock(return_value=docs)), patch(
            "app.services.documents.document_service.pg_service.find_document_by_hash",
            return_value={"id": "doc-1"},
        ) as find_duplicate:
            duplicate = await document_service.ingest_website(url="https://example.com", class_id="class-1")
        self.assertFalse(duplicate["isNew"])
        self.assertEqual(find_duplicate.call_args.args[1], "class-1")

        progress = AsyncMock()
        with patch("app.services.documents.document_service.load_markdown", AsyncMock(return_value=[markdown_doc("Actual website content")])), patch(
            "app.services.documents.document_service.pg_service.find_document_by_hash",
            return_value=None,
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_LEGACY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "doc-2"},
        ), patch(
            "app.services.documents.document_service.publish_progress",
            progress,
        ):
            result = await document_service.ingest_website(
                url="https://example.com",
                client_id="client-1",
                class_id="class-1",
            )

        self.assertEqual(result["fileId"], "doc-2")
        self.assertEqual(progress.await_count, 3)

        with patch("app.services.documents.document_service.pg_service.find_document_by_hash", return_value=None), patch(
            "app.services.documents.document_service.extract_pdf_content_by_page",
            AsyncMock(return_value=pdf_pages("This page contains enough text to be chunked.")),
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], [[2.0]])),
        ), patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_V2_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "racing-doc", "isNew": False},
        ):
            racing_file = await document_service.ingest_document(
                filename="notes.pdf",
                content=b"pdf",
                size=3,
                mimetype="application/pdf",
                class_id="class-1",
            )
        self.assertEqual(racing_file["fileId"], "racing-doc")
        self.assertFalse(racing_file["isNew"])
        self.assertEqual(racing_file["chunksCount"], 0)

        with patch(
            "app.services.documents.document_service.load_markdown",
            AsyncMock(return_value=[markdown_doc("Actual website content")]),
        ), patch(
            "app.services.documents.document_service.pg_service.find_document_by_hash",
            return_value=None,
        ), patch(
            "app.services.documents.document_service._embed_chunks_for_storage",
            AsyncMock(return_value=([[1.0]], None)),
        ), patch(
            "app.services.documents.document_service.get_settings",
            return_value=FALLBACK_LEGACY_SETTINGS,
        ), patch(
            "app.services.documents.document_service.pg_service.create_graph_from_document",
            return_value={"fileId": "racing-link", "isNew": False},
        ), patch(
            "app.services.documents.document_service.publish_progress",
            AsyncMock(),
        ):
            racing_website = await document_service.ingest_website(
                url="https://example.com",
                client_id="client-1",
                class_id="class-1",
            )
        self.assertEqual(racing_website["fileId"], "racing-link")
        self.assertFalse(racing_website["isNew"])
