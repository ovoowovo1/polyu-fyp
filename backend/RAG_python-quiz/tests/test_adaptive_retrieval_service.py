import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services import adaptive_retrieval_service
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


def make_doc(text, *, chunk_id="chunk-1", source="doc.pdf", page=1, file_id="file-1", score=0.12):
    return {
        "text": text,
        "source": source,
        "page": page,
        "fileId": file_id,
        "chunkId": chunk_id,
        "score": score,
    }


async def collect_result(question="hello", selected_file_ids=None, **kwargs):
    if selected_file_ids is None:
        selected_file_ids = ["file-1"]
    return await adaptive_retrieval_service.run_adaptive_retrieval(
        question,
        selected_file_ids,
        **kwargs,
    )


class AdaptiveRetrievalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rrf_and_vector_wrapper_helpers(self):
        fused = adaptive_retrieval_service._reciprocal_rank_fusion(
            [
                [{"chunkId": None, "text": "ignored"}],
                [{"chunkId": "chunk-1", "text": "kept"}],
            ]
        )
        self.assertEqual(
            fused,
            [{"chunkId": "chunk-1", "text": "kept", "content": "kept", "source": "Unknown source", "page": "Unknown page", "fileId": None, "rrf_score": 0.0164}],
        )

        with patch(
            "app.services.adaptive_retrieval_service.retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ) as retrieve_vector_context:
            rows, mode = await adaptive_retrieval_service._retrieve_vector_context(
                "hello",
                ["file-1"],
                k=9,
                log_prefix="ExamRetriever",
            )

        self.assertEqual(rows, [])
        self.assertEqual(mode, "primary")
        retrieve_vector_context.assert_awaited_once_with(
            "hello",
            ["file-1"],
            k=9,
            log_prefix="ExamRetriever",
        )

    async def test_run_adaptive_retrieval_handles_empty_selection(self):
        result = await collect_result(selected_file_ids=[])

        self.assertEqual(result["documents"], [])
        self.assertEqual(result["fallback_reason"], adaptive_retrieval_service.EMPTY_SELECTION_FALLBACK_REASON)
        self.assertEqual(result["retrieval_mode_summary"]["vector_hits"], 0)

    async def test_retrieve_documents_node_tracks_failures_and_candidate_summary(self):
        emitted = []

        async def emit(message, data=None, event_type="retrieval"):
            emitted.append((message, data, event_type))

        state = {
            "question": "hello",
            "original_question": "hello",
            "current_query": "hello",
            "selected_file_ids": ["file-1"],
        }

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            side_effect=RuntimeError("fts failed"),
        ):
            updated = await adaptive_retrieval_service.retrieve_documents_node(state, emit)

        self.assertEqual(updated["candidate_documents"], [])
        self.assertTrue(updated["vector_retrieval_degraded"])
        self.assertTrue(updated["retrieval_mode_summary"]["vector_failed"])
        self.assertTrue(updated["retrieval_mode_summary"]["fulltext_failed"])
        self.assertTrue(emitted)

    async def test_grade_documents_and_rewrite_fallback_branches(self):
        emitted = []

        async def emit(message, data=None, event_type="retrieval"):
            emitted.append((message, data, event_type))

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader down")),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "hello",
                    "candidate_documents": [make_doc("ctx")],
                },
                emit,
            )
        self.assertEqual(len(graded["filtered_documents"]), 1)

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("rewrite down")),
        ):
            rewritten = await adaptive_retrieval_service.rewrite_query_node(
                {
                    "question": "hello",
                    "original_question": "hello",
                    "current_query": "hello",
                },
                emit,
                max_rewrite_attempts=2,
            )
        self.assertEqual(rewritten["current_query"], "hello")
        self.assertEqual(rewritten["rewrite_count"], 1)
        self.assertTrue(emitted)

    async def test_grade_documents_runs_in_parallel_preserves_order_and_keeps_failed_chunks(self):
        emitted = []

        async def emit(message, data=None, event_type="retrieval"):
            emitted.append((message, data, event_type))

        docs = [
            make_doc("doc one", chunk_id="chunk-1"),
            make_doc("doc two", chunk_id="chunk-2"),
            make_doc("doc three", chunk_id="chunk-3"),
        ]
        call_order = []

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if "doc one" in prompt:
                await asyncio.sleep(0.03)
                call_order.append("chunk-1")
                return {"relevant": "yes", "reason": "keep"}
            if "doc two" in prompt:
                await asyncio.sleep(0.01)
                call_order.append("chunk-2")
                raise RuntimeError("grader down")
            if "doc three" in prompt:
                call_order.append("chunk-3")
                return {"relevant": "no", "reason": "drop"}
            raise AssertionError(prompt)

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "hello",
                    "candidate_documents": docs,
                },
                emit,
            )

        self.assertEqual(call_order, ["chunk-3", "chunk-2", "chunk-1"])
        self.assertEqual(
            [doc["chunkId"] for doc in graded["filtered_documents"]],
            ["chunk-1", "chunk-2"],
        )
        self.assertTrue(emitted)

    async def test_grade_documents_supports_bounded_concurrency_branch(self):
        emitted = []

        async def emit(message, data=None, event_type="retrieval"):
            emitted.append((message, data, event_type))

        with patch.object(adaptive_retrieval_service, "DOCUMENT_GRADING_CONCURRENCY", 1), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(return_value={"relevant": "yes", "reason": "keep"}),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "hello",
                    "candidate_documents": [make_doc("ctx", chunk_id="chunk-9")],
                },
                emit,
            )

        self.assertEqual([doc["chunkId"] for doc in graded["filtered_documents"]], ["chunk-9"])
        self.assertTrue(emitted)

    async def test_run_adaptive_retrieval_uses_fulltext_when_vector_fails(self):
        fulltext_result = [make_doc("fulltext chunk")]

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "yes", "reason": "match"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=fulltext_result,
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            result = await collect_result()

        self.assertEqual(result["documents"][0]["chunkId"], "chunk-1")
        self.assertTrue(result["vector_retrieval_degraded"])
        self.assertIsNone(result["fallback_reason"])

    async def test_run_adaptive_retrieval_rewrites_then_succeeds(self):
        doc = make_doc("rewritten query hit")

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG rewrite query":
                return {"rewritten_query": "better query"}
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "yes", "reason": "match"}
            raise AssertionError(operation_name)

        retrieve_vector_context = AsyncMock(side_effect=[([], "primary"), ([doc], "primary")])
        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            retrieve_vector_context,
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            result = await collect_result()

        self.assertEqual(result["documents"][0]["chunkId"], "chunk-1")
        self.assertEqual(result["rewrite_count"], 1)
        self.assertEqual(result["current_query"], "better query")
        self.assertEqual(retrieve_vector_context.await_count, 2)

    async def test_run_adaptive_retrieval_returns_no_documents_after_rewrite_limit(self):
        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG rewrite query":
                return {"rewritten_query": "better query"}
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "no", "reason": "irrelevant"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            result = await collect_result()

        self.assertEqual(result["documents"], [])
        self.assertEqual(result["fallback_reason"], adaptive_retrieval_service.NO_RELEVANT_DOCUMENTS_FALLBACK_REASON)
