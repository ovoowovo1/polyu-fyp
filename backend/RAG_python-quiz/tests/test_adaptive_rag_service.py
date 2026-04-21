import unittest
from unittest.mock import AsyncMock, patch

from app.services import adaptive_rag_service
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


def make_answer_response(*, valid_chunk_id="chunk-1", include_invalid_ref=False):
    refs = [{"file_chunk_id": valid_chunk_id}]
    if include_invalid_ref:
        refs.append({"file_chunk_id": "chunk-invalid"})
    return {
        "answer": "Grounded answer.",
        "answer_with_citations": [
            {
                "content_segments": [
                    {
                        "segment_text": "Grounded answer.",
                        "source_references": refs,
                    }
                ]
            }
        ],
    }


async def collect_events(question="hello", selected_file_ids=None):
    if selected_file_ids is None:
        selected_file_ids = ["file-1"]
    events = []
    async for event in adaptive_rag_service.run_adaptive_rag_stream(question, selected_file_ids):
        events.append(event)
    return events


class AdaptiveRAGServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rrf_skips_documents_without_chunk_ids(self):
        fused = adaptive_rag_service._reciprocal_rank_fusion(
            [
                [{"chunkId": None, "text": "ignored"}],
                [{"chunkId": "chunk-1", "text": "kept"}],
            ]
        )

        self.assertEqual(fused, [{"chunkId": "chunk-1", "text": "kept", "content": "kept", "source": "Unknown source", "page": "Unknown page", "fileId": None, "rrf_score": 0.0164}])

    async def test_helper_functions_cover_text_sanitization_and_payload(self):
        self.assertEqual(adaptive_rag_service._extract_answer_text("bad"), "")
        self.assertEqual(
            adaptive_rag_service._extract_answer_text(
                [{"content_segments": [{"segment_text": " first "}, {"segment_text": "second"}]}]
            ),
            "first\n\nsecond",
        )
        self.assertEqual(adaptive_rag_service._sanitize_answer_with_citations("bad", ["chunk-1"]), [])
        self.assertEqual(
            adaptive_rag_service._sanitize_answer_with_citations(
                [
                    {
                        "content_segments": [
                            {
                                "segment_text": "kept",
                                "source_references": [{"file_chunk_id": "chunk-1"}],
                            },
                            {
                                "segment_text": "dropped",
                                "source_references": [{"file_chunk_id": "chunk-x"}],
                            },
                        ]
                    }
                ],
                ["chunk-1"],
            ),
            [{"content_segments": [{"segment_text": "kept", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
        )
        payload = adaptive_rag_service._build_result_payload(
            state={"result_reason": "why"},
            question=" q ",
            answer="a",
            answer_with_citations=[],
            raw_sources=[{"text": "ctx", "rrf_score": 0.5}],
        )
        self.assertEqual(payload["question"], "q")
        self.assertEqual(payload["raw_sources"][0]["source"], "Unknown source")

    async def test_wrapper_delegates_to_shared_vector_service(self):
        with patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ) as retrieve_vector_context:
            rows, mode = await adaptive_rag_service._retrieve_vector_context("hello", ["file-1"])

        self.assertEqual(rows, [])
        self.assertEqual(mode, "primary")
        retrieve_vector_context.assert_awaited_once_with(
            "hello",
            ["file-1"],
            k=20,
            log_prefix="vector retrieval",
        )

    async def test_route_reject_returns_conservative_result(self):
        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"decision": "reject", "reason": "needs external info"}),
        ):
            events = await collect_events("what happened today in hong kong?")

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["answer"], adaptive_rag_service.OUT_OF_SCOPE_ANSWER)
        self.assertEqual(events[-1]["result_reason"], adaptive_rag_service.UNSUPPORTED_RESULT_REASON)

    async def test_vector_failure_still_uses_fulltext_results(self):
        fulltext_result = [make_doc("fulltext chunk")]

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG route question":
                return {"decision": "retrieve", "reason": "document question"}
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "yes", "reason": "match"}
            if operation_name == "Adaptive RAG grade generation":
                return {"grounded": "yes", "answers_question": "yes", "reason": "ok"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=fulltext_result,
        ), patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_with_langchain",
            AsyncMock(return_value=make_answer_response()),
        ):
            events = await collect_events()

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["answer"], "Grounded answer.")
        self.assertEqual(events[-1]["raw_sources"][0]["chunkId"], "chunk-1")
        self.assertTrue(any(event["type"] == "retrieval" for event in events))

    async def test_route_question_and_rewrite_fallback_branches(self):
        emitted = []

        async def emit(message, data=None, event_type="progress"):
            emitted.append((message, data, event_type))

        state = {"question": "hello", "original_question": "hello"}
        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("down")),
        ):
            state = await adaptive_rag_service.route_question_node(state, emit)
        self.assertEqual(state["route_decision"], "retrieve")

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("down")),
        ):
            rewritten = await adaptive_rag_service.rewrite_query_node(state, emit)
        self.assertEqual(rewritten["current_query"], "hello")
        self.assertTrue(emitted)

    async def test_retrieve_documents_fulltext_failure_and_document_grading_fallback(self):
        emitted = []

        async def emit(message, data=None, event_type="progress"):
            emitted.append((message, data, event_type))

        state = {
            "question": "hello",
            "current_query": "hello",
            "selected_file_ids": ["file-1"],
            "candidate_documents": [],
        }
        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([make_doc("vector doc")], "primary")),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            side_effect=RuntimeError("fts failed"),
        ):
            state = await adaptive_rag_service.retrieve_documents_node(state, emit)
        self.assertEqual(len(state["candidate_documents"]), 1)

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader down")),
        ):
            graded = await adaptive_rag_service.grade_documents_node(
                {"question": "hello", "candidate_documents": state["candidate_documents"]},
                emit,
            )
        self.assertEqual(len(graded["filtered_documents"]), 1)
        self.assertTrue(emitted)

    async def test_rewrite_query_after_empty_retrieval_then_success(self):
        doc = make_doc("rewritten query hit")

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG route question":
                return {"decision": "retrieve", "reason": "document question"}
            if operation_name == "Adaptive RAG rewrite query":
                return {"rewritten_query": "better query"}
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "yes", "reason": "match"}
            if operation_name == "Adaptive RAG grade generation":
                return {"grounded": "yes", "answers_question": "yes", "reason": "ok"}
            raise AssertionError(operation_name)

        retrieve_vector_context = AsyncMock(side_effect=[([], "primary"), ([doc], "primary")])
        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            retrieve_vector_context,
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_with_langchain",
            AsyncMock(return_value=make_answer_response()),
        ):
            events = await collect_events()

        self.assertEqual(events[-1]["answer"], "Grounded answer.")
        self.assertEqual(retrieve_vector_context.await_count, 2)
        self.assertTrue(any(event["type"] == "rewrite" for event in events))

    async def test_document_grading_filters_irrelevant_chunks(self):
        relevant_doc = make_doc("database normalization", chunk_id="chunk-1")
        irrelevant_doc = make_doc("football news", chunk_id="chunk-2")

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG route question":
                return {"decision": "retrieve", "reason": "document question"}
            if operation_name == "Adaptive RAG grade document":
                if "football news" in prompt:
                    return {"relevant": "no", "reason": "irrelevant"}
                return {"relevant": "yes", "reason": "relevant"}
            if operation_name == "Adaptive RAG grade generation":
                return {"grounded": "yes", "answers_question": "yes", "reason": "ok"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([relevant_doc, irrelevant_doc], "primary")),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_with_langchain",
            AsyncMock(return_value=make_answer_response(valid_chunk_id="chunk-1", include_invalid_ref=True)),
        ):
            events = await collect_events("Explain normalization")

        result = events[-1]
        self.assertEqual(len(result["raw_sources"]), 1)
        self.assertEqual(result["raw_sources"][0]["chunkId"], "chunk-1")
        refs = result["answer_with_citations"][0]["content_segments"][0]["source_references"]
        self.assertEqual(refs, [{"file_chunk_id": "chunk-1"}])

    async def test_unreliable_generation_retries_once_then_returns_conservative_result(self):
        doc = make_doc("transaction isolation")

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG route question":
                return {"decision": "retrieve", "reason": "document question"}
            if operation_name == "Adaptive RAG grade document":
                return {"relevant": "yes", "reason": "relevant"}
            if operation_name == "Adaptive RAG rewrite query":
                return {"rewritten_query": "transaction isolation levels"}
            if operation_name == "Adaptive RAG grade generation":
                return {"grounded": "no", "answers_question": "no", "reason": "bad answer"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([doc], "primary")),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_with_langchain",
            AsyncMock(return_value=make_answer_response()),
        ):
            events = await collect_events("Explain transaction isolation")

        result = events[-1]
        self.assertEqual(result["answer"], adaptive_rag_service.NO_DOCUMENTS_ANSWER)
        self.assertEqual(result["result_reason"], adaptive_rag_service.UNRELIABLE_RESULT_REASON)
        self.assertEqual(result["raw_sources"][0]["chunkId"], "chunk-1")

    async def test_grade_generation_covers_empty_answer_and_grader_failure(self):
        emitted = []

        async def emit(message, data=None, event_type="progress"):
            emitted.append((message, data, event_type))

        state = await adaptive_rag_service.grade_generation_node(
            {"filtered_documents": [], "answer": "", "answer_with_citations": []},
            emit,
        )
        self.assertEqual(state["result_reason"], adaptive_rag_service.UNRELIABLE_RESULT_REASON)

        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader down")),
        ):
            state = await adaptive_rag_service.grade_generation_node(
                {
                    "question": "hello",
                    "filtered_documents": [make_doc("ctx")],
                    "answer": "ok",
                    "answer_with_citations": [{"content_segments": [{"segment_text": "ok", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
                },
                emit,
            )
        self.assertNotIn("result_reason", state)
        self.assertTrue(emitted)

    async def test_stream_returns_no_documents_reason_after_rewrite_limit(self):
        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            if operation_name == "Adaptive RAG route question":
                return {"decision": "retrieve", "reason": "document question"}
            if operation_name == "Adaptive RAG rewrite query":
                return {"rewritten_query": "better query"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            return_value=[],
        ), patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            events = await collect_events("still nothing")

        result = events[-1]
        self.assertEqual(result["answer"], adaptive_rag_service.NO_DOCUMENTS_ANSWER)
        self.assertEqual(result["result_reason"], adaptive_rag_service.NO_DOCUMENTS_RESULT_REASON)

    async def test_stream_handles_empty_selection(self):
        events = await collect_events(selected_file_ids=[])
        self.assertEqual(events[0]["type"], "retrieval")
        self.assertEqual(events[-1]["message"], "Please select at least one document for retrieval.")
        self.assertEqual(events[-1]["type"], "retrieval")
