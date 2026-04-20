import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import query_stream
from app.utils.ingest_errors import EmbeddingProviderError


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


class QueryStreamRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rrf_skips_documents_without_chunk_ids(self):
        fused = query_stream._reciprocal_rank_fusion(
            [
                [{"chunkId": None, "text": "ignored"}],
                [{"chunkId": "chunk-1", "text": "kept"}],
            ]
        )

        self.assertEqual(fused, [{"chunkId": "chunk-1", "text": "kept", "rrf_score": 0.0164}])

    async def test_wrapper_delegates_to_shared_vector_service(self):
        with patch(
            "app.routers.query_stream.retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ) as retrieve_vector_context:
            rows, mode = await query_stream._retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(rows, [])
        self.assertEqual(mode, "primary")
        retrieve_vector_context.assert_awaited_once_with(
            "hello",
            ["file-1"],
            k=20,
            log_prefix="vector retrieval",
        )

    async def test_stream_continues_with_fulltext_results_when_vector_retrieval_fails(self):
        fulltext_result = [
            {
                "text": "fulltext chunk",
                "source": "doc.pdf",
                "page": 1,
                "fileId": "file-1",
                "chunkId": "chunk-1",
                "score": 0.12,
            }
        ]

        with patch(
            "app.routers.query_stream._retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
        ), patch(
            "app.routers.query_stream.pg_service.retrieve_context_by_keywords",
            return_value=fulltext_result,
        ), patch(
            "app.routers.query_stream.generate_answer_with_langchain",
            AsyncMock(return_value={"answer": "ok", "answer_with_citations": []}),
        ):
            events = []
            async for chunk in query_stream.sse_event_stream("hello", ["file-1"]):
                events.append(json.loads(chunk.decode("utf-8")))

        vector_error_events = [event for event in events if event["type"] == "vector"]
        self.assertTrue(vector_error_events)
        self.assertIn("error occurred", vector_error_events[0]["message"])
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["answer"], "ok")
        self.assertEqual(events[-1]["raw_sources"][0]["chunkId"], "chunk-1")

    async def test_stream_handles_empty_selection_fallback_mode_fulltext_error_and_no_docs(self):
        empty_events = []
        async for chunk in query_stream.sse_event_stream("hello", []):
            empty_events.append(json.loads(chunk.decode("utf-8")))
        self.assertEqual(empty_events[-1]["message"], "Please select at least one document for retrieval.")

        with patch(
            "app.routers.query_stream._retrieve_vector_context",
            AsyncMock(return_value=([], "fallback")),
        ), patch(
            "app.routers.query_stream.pg_service.retrieve_context_by_keywords",
            side_effect=RuntimeError("fts failed"),
        ):
            events = []
            async for chunk in query_stream.sse_event_stream("hello", ["file-1"]):
                events.append(json.loads(chunk.decode("utf-8")))

        event_types = [event["type"] for event in events]
        self.assertIn("vectorProgress", event_types)
        self.assertIn("fulltext", event_types)
        self.assertEqual(events[-1]["answer"], "Sorry, no relevant information was found in the specified documents.")


class QueryStreamRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(query_stream.router)
        self.client = TestClient(app)

    def test_query_stream_route_validates_payload(self):
        missing_question = self.client.post("/query-stream", json={"question": "   ", "selectedFileIds": ["file-1"]})
        self.assertEqual(missing_question.status_code, 400)

        missing_files = self.client.post("/query-stream", json={"question": "hello", "selectedFileIds": []})
        self.assertEqual(missing_files.status_code, 400)

    def test_query_stream_route_returns_streaming_response(self):
        async def fake_stream(question, selected_file_ids):
            yield b'{"type":"result"}\n'

        with patch("app.routers.query_stream.sse_event_stream", fake_stream):
            response = self.client.post("/query-stream", json={"question": "hello", "selectedFileIds": ["file-1"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
