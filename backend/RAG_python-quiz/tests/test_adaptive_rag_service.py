import unittest
from unittest.mock import AsyncMock, patch

from app.services import adaptive_rag_service


class AdaptiveRagServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_helper_functions_and_wrapper_nodes_delegate_correctly(self):
        normalized = adaptive_rag_service._normalize_doc(
            {
                "content": "chunk",
                "document_name": "doc.pdf",
                "pageStart": 3,
                "fileid": "file-1",
                "chunkid": "chunk-1",
            }
        )
        self.assertEqual(normalized["source"], "doc.pdf")
        self.assertEqual(normalized["page"], 3)
        self.assertEqual(normalized["fileId"], "file-1")
        self.assertEqual(normalized["chunkId"], "chunk-1")

        formatted, file_ids, chunk_ids = adaptive_rag_service._format_docs_for_answer([normalized])
        self.assertIn('source_file: "doc.pdf"', formatted)
        self.assertEqual(file_ids, ["file-1"])
        self.assertEqual(chunk_ids, ["chunk-1"])

        extracted = adaptive_rag_service._extract_answer_text(
            [{"content_segments": [{"segment_text": "One"}, {"segment_text": "Two"}]}]
        )
        self.assertEqual(extracted, "One\n\nTwo")
        self.assertEqual(adaptive_rag_service._extract_answer_text("bad"), "")
        self.assertEqual(
            adaptive_rag_service._sanitize_answer_with_citations(
                [{"content_segments": [{"segment_text": "One", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
                ["chunk-1"],
            ),
            [{"content_segments": [{"segment_text": "One", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
        )
        self.assertEqual(
            adaptive_rag_service._sanitize_answer_with_citations(
                [{"content_segments": [{"segment_text": "One", "source_references": [{"file_chunk_id": "missing"}]}]}],
                ["chunk-1"],
            ),
            [],
        )
        self.assertEqual(adaptive_rag_service._sanitize_answer_with_citations("bad", ["chunk-1"]), [])

        async def emit(message, data=None, event_type="retrieval"):
            del message, data, event_type

        with patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service._reciprocal_rank_fusion",
            return_value=[{"chunkId": "chunk-1"}],
        ) as reciprocal_rank_fusion, patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ) as retrieve_vector_context, patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service.retrieve_documents_node",
            AsyncMock(return_value={"step": "retrieve"}),
        ) as retrieve_documents_node, patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service.grade_documents_node",
            AsyncMock(return_value={"step": "grade"}),
        ) as grade_documents_node, patch(
            "app.services.adaptive_rag_service.adaptive_retrieval_service.rewrite_query_node",
            AsyncMock(return_value={"step": "rewrite"}),
        ) as rewrite_query_node:
            self.assertEqual(adaptive_rag_service._reciprocal_rank_fusion([[]]), [{"chunkId": "chunk-1"}])
            self.assertEqual(
                await adaptive_rag_service._retrieve_vector_context("question", ["file-1"]),
                ([], "primary"),
            )
            self.assertEqual(
                await adaptive_rag_service.retrieve_documents_node({"question": "q"}, emit),
                {"step": "retrieve"},
            )
            self.assertEqual(
                await adaptive_rag_service.grade_documents_node({"question": "q"}, emit),
                {"step": "grade"},
            )
            self.assertEqual(
                await adaptive_rag_service.rewrite_query_node({"question": "q"}, emit),
                {"step": "rewrite"},
            )

        reciprocal_rank_fusion.assert_called_once()
        retrieve_vector_context.assert_awaited_once_with(
            "question",
            ["file-1"],
            k=adaptive_rag_service.RETRIEVAL_K,
            log_prefix="vector retrieval",
        )
        retrieve_documents_node.assert_awaited_once()
        grade_documents_node.assert_awaited_once()
        rewrite_query_node.assert_awaited_once()

    async def test_generate_answer_node_uses_citation_evidence_result(self):
        state = {
            "question": "What is CAP theorem?",
            "filtered_documents": [
                {
                    "text": "CAP theorem describes trade-offs.",
                    "source": "notes.pdf",
                    "page": 1,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ],
        }

        async def emit(message, data=None, event_type="retrieval"):
            del message, data, event_type

        with patch(
            "app.services.adaptive_rag_service.citation_evidence_service.generate_citation_evidence",
            AsyncMock(
                return_value={
                    "answer_text": "CAP theorem is a trade-off.",
                    "citations": [{"chunk_id": "chunk-1", "file_id": "file-1", "source": "notes.pdf", "page": 1}],
                    "answer_with_citations": [
                        {
                            "content_segments": [
                                {
                                    "segment_text": "CAP theorem is a trade-off.",
                                    "source_references": [{"file_chunk_id": "chunk-1"}],
                                }
                            ]
                        }
                    ],
                    "raw_sources": [
                        {
                            "content": "CAP theorem describes trade-offs.",
                            "source": "notes.pdf",
                            "pageNumber": 1,
                            "score": None,
                            "fileId": "file-1",
                            "chunkId": "chunk-1",
                        }
                    ],
                    "evidence_nodes": [
                        {
                            "node_id": "chunk-1",
                            "file_id": "file-1",
                            "chunk_id": "chunk-1",
                            "source": "notes.pdf",
                            "page": 1,
                            "text": "CAP theorem describes trade-offs.",
                            "score": None,
                        }
                    ],
                    "required_concepts": [],
                    "covered_concepts": [],
                    "missing_concepts": [],
                    "coverage_status": "complete",
                }
            ),
        ) as generate_citation_evidence:
            result = await adaptive_rag_service.generate_answer_node(state, emit)

        generate_citation_evidence.assert_awaited_once_with(
            "What is CAP theorem?",
            state["filtered_documents"],
            required_concepts=[],
            covered_concepts=[],
            intent_type="single",
        )
        self.assertEqual(result["answer"], "CAP theorem is a trade-off.")
        self.assertEqual(result["citations"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["answer_with_citations"][0]["content_segments"][0]["segment_text"], "CAP theorem is a trade-off.")
        self.assertEqual(result["raw_sources"][0]["chunkId"], "chunk-1")
        self.assertEqual(result["evidence_nodes"][0]["node_id"], "chunk-1")
        self.assertEqual(result["result_reason"], None)

    def test_build_result_payload_normalizes_sources_for_response(self):
        payload = adaptive_rag_service._build_result_payload(
            state={"result_reason": None},
            question="  explain cap  ",
            answer="answer",
            answer_with_citations=[],
            raw_sources=[
                {
                    "text": "chunk text",
                    "source": "doc.pdf",
                    "page": 4,
                    "score": 0.2,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ],
        )

        self.assertEqual(payload["question"], "explain cap")
        self.assertEqual(
            payload["raw_sources"],
            [
                {
                    "content": "chunk text",
                    "source": "doc.pdf",
                    "pageNumber": 4,
                    "score": 0.2,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ],
        )

    async def test_route_question_node_and_grade_generation_cover_key_branches(self):
        events = []

        async def emit(message, data=None, event_type="retrieval"):
            events.append((message, data, event_type))

        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"decision": "reject", "reason": "out of scope"}),
        ):
            routed = await adaptive_rag_service.route_question_node(
                {"question": "weather today", "selected_file_ids": ["file-1"]},
                emit,
            )

        self.assertEqual(routed["route_decision"], "reject")
        self.assertEqual(events[0][2], "router")

        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            fallback_route = await adaptive_rag_service.route_question_node(
                {"question": "course notes", "selected_file_ids": ["file-1"]},
                emit,
            )

        self.assertEqual(fallback_route["route_decision"], "retrieve")

        missing_answer_state = await adaptive_rag_service.grade_generation_node(
            {"answer": "", "answer_with_citations": [], "filtered_documents": []},
            emit,
        )
        self.assertEqual(missing_answer_state["result_reason"], adaptive_rag_service.UNRELIABLE_RESULT_REASON)

        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"grounded": "yes", "coverage_status": "full", "reason": "ok"}),
        ):
            citation_only_state = await adaptive_rag_service.grade_generation_node(
                {
                    "question": "What is CAP theorem?",
                    "answer": "Grounded answer.",
                    "answer_with_citations": [],
                    "citations": [{"chunk_id": "chunk-1"}],
                    "filtered_documents": [{"source": "doc.pdf", "page": 1, "text": "CAP theorem text"}],
                    "query_intent": {"required_concepts": []},
                    "covered_concepts": [],
                    "missing_concepts": [],
                },
                emit,
            )
        self.assertNotEqual(citation_only_state.get("result_reason"), adaptive_rag_service.UNRELIABLE_RESULT_REASON)

        accepted_state = {
            "question": "What is CAP theorem?",
            "answer": "Grounded answer.",
            "answer_with_citations": [{"content_segments": [{"segment_text": "Grounded answer.", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
            "filtered_documents": [{"source": "doc.pdf", "page": 1, "text": "CAP theorem text"}],
            "query_intent": {"required_concepts": []},
            "covered_concepts": [],
            "missing_concepts": [],
        }
        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"grounded": "yes", "coverage_status": "full", "reason": "ok"}),
        ):
            accepted = await adaptive_rag_service.grade_generation_node(accepted_state, emit)
        self.assertIsNone(accepted["result_reason"])

        partial_state = {
            "question": "What is SQL and NoSQL?",
            "answer": "NoSQL uses flexible schemas.\n\nThe selected documents do not provide enough reliable information about SQL.",
            "answer_with_citations": [{"content_segments": [{"segment_text": "NoSQL uses flexible schemas.", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
            "filtered_documents": [{"source": "doc.pdf", "page": 1, "text": "NoSQL uses flexible schemas."}],
            "query_intent": {"required_concepts": ["SQL", "NoSQL"]},
            "covered_concepts": ["NoSQL"],
            "missing_concepts": ["SQL"],
        }
        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"grounded": "yes", "coverage_status": "partial", "reason": "limited but honest"}),
        ):
            partial = await adaptive_rag_service.grade_generation_node(partial_state, emit)
        self.assertEqual(partial["result_reason"], adaptive_rag_service.PARTIAL_COVERAGE_RESULT_REASON)

        rejected_state = {
            "question": "What is CAP theorem?",
            "answer": "Ungrounded answer.",
            "answer_with_citations": [{"content_segments": [{"segment_text": "Ungrounded answer.", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
            "filtered_documents": [{"source": "doc.pdf", "page": 1, "text": "CAP theorem text"}],
            "query_intent": {"required_concepts": []},
            "covered_concepts": [],
            "missing_concepts": [],
        }
        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(return_value={"grounded": "no", "coverage_status": "insufficient", "reason": "hallucinated"}),
        ):
            rejected = await adaptive_rag_service.grade_generation_node(rejected_state, emit)
        self.assertEqual(rejected["result_reason"], adaptive_rag_service.UNRELIABLE_RESULT_REASON)

        with patch(
            "app.services.adaptive_rag_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader unavailable")),
        ):
            accepted_on_error = await adaptive_rag_service.grade_generation_node(
                {
                    "question": "What is CAP theorem?",
                    "answer": "Grounded answer.",
                    "answer_with_citations": [{"content_segments": [{"segment_text": "Grounded answer.", "source_references": [{"file_chunk_id": "chunk-1"}]}]}],
                    "filtered_documents": [{"source": "doc.pdf", "page": 1, "text": "CAP theorem text"}],
                    "query_intent": {"required_concepts": []},
                    "covered_concepts": [],
                    "missing_concepts": [],
                },
                emit,
            )
        self.assertNotIn("result_reason", accepted_on_error)

    async def test_run_adaptive_rag_stream_success_path_keeps_backward_compatible_payload(self):
        async def fake_route(state, emit):
            await emit("router event", event_type="router")
            state["route_decision"] = "retrieve"
            return state

        async def fake_retrieve(state, emit):
            await emit("retrieved", 1, "retrieval")
            state["candidate_documents"] = [{"chunkId": "chunk-1"}]
            return state

        async def fake_grade_docs(state, emit):
            await emit("graded docs", 1, "grader")
            state["filtered_documents"] = [
                {
                    "text": "chunk text",
                    "source": "doc.pdf",
                    "page": 2,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ]
            return state

        async def fake_generate(state, emit):
            await emit("generated", 1, "generation")
            state["answer"] = "Grounded answer."
            state["citations"] = [{"chunk_id": "chunk-1", "file_id": "file-1", "source": "doc.pdf", "page": 2}]
            state["answer_with_citations"] = [
                {
                    "content_segments": [
                        {
                            "segment_text": "Grounded answer.",
                            "source_references": [{"file_chunk_id": "chunk-1"}],
                        }
                    ]
                }
            ]
            state["raw_sources"] = [
                {
                    "content": "chunk text",
                    "source": "doc.pdf",
                    "pageNumber": 2,
                    "score": None,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ]
            state["evidence_nodes"] = [{"node_id": "chunk-1"}]
            state["covered_concepts"] = []
            state["missing_concepts"] = []
            return state

        async def fake_grade_generation(state, emit):
            await emit("graded answer", 1, "grader")
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", fake_route), patch(
            "app.services.adaptive_rag_service.retrieve_documents_node",
            fake_retrieve,
        ), patch(
            "app.services.adaptive_rag_service.grade_documents_node",
            fake_grade_docs,
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_node",
            fake_generate,
        ), patch(
            "app.services.adaptive_rag_service.grade_generation_node",
            fake_grade_generation,
        ):
            events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", ["file-1"])]

        result_event = events[-1]
        self.assertEqual(result_event["type"], "result")
        self.assertEqual(result_event["answer"], "Grounded answer.")
        self.assertEqual(result_event["answer_with_citations"][0]["content_segments"][0]["segment_text"], "Grounded answer.")
        self.assertEqual(result_event["raw_sources"][0]["chunkId"], "chunk-1")
        self.assertEqual(events[1]["type"], "router")

    async def test_run_adaptive_rag_stream_covers_empty_reject_retry_and_rewrite_limit_paths(self):
        empty_events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", [])]
        self.assertEqual(empty_events[-1]["message"], "Please select at least one document for retrieval.")

        async def reject_route(state, emit):
            del emit
            state["route_decision"] = "reject"
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", reject_route):
            reject_events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", ["file-1"])]
        self.assertEqual(reject_events[-1]["answer"], adaptive_rag_service.OUT_OF_SCOPE_ANSWER)

        async def retry_route(state, emit):
            del emit
            state["route_decision"] = "retrieve"
            return state

        async def retry_retrieve(state, emit):
            del emit
            state["filtered_documents"] = [{"chunkId": "chunk-1"}]
            return state

        async def retry_grade_docs(state, emit):
            del emit
            return state

        async def retry_generate(state, emit):
            del emit
            state["answer"] = "Answer"
            state["answer_with_citations"] = [{"content_segments": [{"segment_text": "Answer", "source_references": [{"file_chunk_id": "chunk-1"}]}]}]
            state["raw_sources"] = [{"content": "text", "source": "doc.pdf", "pageNumber": 1, "score": None, "fileId": "file-1", "chunkId": "chunk-1"}]
            return state

        async def retry_grade_generation(state, emit):
            del emit
            state["result_reason"] = adaptive_rag_service.UNRELIABLE_RESULT_REASON
            state["generation_retry_count"] = adaptive_rag_service.MAX_GENERATION_RETRIES
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", retry_route), patch(
            "app.services.adaptive_rag_service.retrieve_documents_node",
            retry_retrieve,
        ), patch(
            "app.services.adaptive_rag_service.grade_documents_node",
            retry_grade_docs,
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_node",
            retry_generate,
        ), patch(
            "app.services.adaptive_rag_service.grade_generation_node",
            retry_grade_generation,
        ):
            retry_events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", ["file-1"])]
        self.assertEqual(retry_events[-1]["answer"], adaptive_rag_service.NO_DOCUMENTS_ANSWER)

        async def rewrite_limit_retrieve(state, emit):
            del emit
            state["filtered_documents"] = []
            state["rewrite_count"] = adaptive_rag_service.MAX_REWRITE_ATTEMPTS
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", retry_route), patch(
            "app.services.adaptive_rag_service.retrieve_documents_node",
            rewrite_limit_retrieve,
        ), patch(
            "app.services.adaptive_rag_service.grade_documents_node",
            retry_grade_docs,
        ):
            rewrite_events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", ["file-1"])]
        self.assertEqual(rewrite_events[-1]["result_reason"], adaptive_rag_service.NO_DOCUMENTS_RESULT_REASON)

    async def test_run_adaptive_rag_stream_retries_generation_then_rewrites_query(self):
        call_state = {"retrieve_calls": 0}

        async def retry_route(state, emit):
            del emit
            state["route_decision"] = "retrieve"
            return state

        async def retrieve_after_retry(state, emit):
            del emit
            call_state["retrieve_calls"] += 1
            if call_state["retrieve_calls"] == 1:
                state["filtered_documents"] = [{"chunkId": "chunk-1"}]
                state["rewrite_count"] = 0
            else:
                state["filtered_documents"] = []
                state["rewrite_count"] = adaptive_rag_service.MAX_REWRITE_ATTEMPTS
            return state

        async def passthrough(state, emit):
            del emit
            return state

        async def retry_generate(state, emit):
            del emit
            state["answer"] = "Answer"
            state["answer_with_citations"] = [{"content_segments": [{"segment_text": "Answer", "source_references": [{"file_chunk_id": "chunk-1"}]}]}]
            state["raw_sources"] = [{"content": "text", "source": "doc.pdf", "pageNumber": 1, "score": None, "fileId": "file-1", "chunkId": "chunk-1"}]
            return state

        async def retry_grade_generation(state, emit):
            del emit
            state["result_reason"] = adaptive_rag_service.UNRELIABLE_RESULT_REASON
            return state

        async def rewrite_query(state, emit):
            await emit("rewritten", event_type="rewrite")
            state["current_query"] = "rewritten query"
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", retry_route), patch(
            "app.services.adaptive_rag_service.retrieve_documents_node",
            retrieve_after_retry,
        ), patch(
            "app.services.adaptive_rag_service.grade_documents_node",
            passthrough,
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_node",
            retry_generate,
        ), patch(
            "app.services.adaptive_rag_service.grade_generation_node",
            retry_grade_generation,
        ), patch(
            "app.services.adaptive_rag_service.rewrite_query_node",
            rewrite_query,
        ):
            events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("question", ["file-1"])]

        self.assertEqual(events[-1]["result_reason"], adaptive_rag_service.UNRELIABLE_RESULT_REASON)
        self.assertIn("rewritten", [event.get("message") for event in events])

    async def test_run_adaptive_rag_stream_returns_partial_coverage_result_without_retry_loop(self):
        async def route(state, emit):
            del emit
            state["route_decision"] = "retrieve"
            return state

        async def retrieve(state, emit):
            del emit
            state["candidate_documents"] = [{"chunkId": "chunk-1"}]
            return state

        async def grade_docs(state, emit):
            del emit
            state["filtered_documents"] = [
                {
                    "text": "NoSQL uses flexible schemas.",
                    "source": "doc.pdf",
                    "page": 2,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ]
            state["covered_concepts"] = ["NoSQL"]
            state["missing_concepts"] = ["SQL"]
            state["query_intent"] = {"required_concepts": ["SQL", "NoSQL"]}
            return state

        async def generate(state, emit):
            del emit
            state["answer"] = "NoSQL uses flexible schemas.\n\nThe selected documents do not provide enough reliable information about SQL."
            state["answer_with_citations"] = [
                {
                    "content_segments": [
                        {
                            "segment_text": "NoSQL uses flexible schemas.",
                            "source_references": [{"file_chunk_id": "chunk-1"}],
                        }
                    ]
                }
            ]
            state["raw_sources"] = [
                {
                    "content": "NoSQL uses flexible schemas.",
                    "source": "doc.pdf",
                    "pageNumber": 2,
                    "score": None,
                    "fileId": "file-1",
                    "chunkId": "chunk-1",
                }
            ]
            state["result_reason"] = adaptive_rag_service.PARTIAL_COVERAGE_RESULT_REASON
            return state

        async def grade_generation(state, emit):
            del emit
            state["result_reason"] = adaptive_rag_service.PARTIAL_COVERAGE_RESULT_REASON
            return state

        with patch("app.services.adaptive_rag_service.route_question_node", route), patch(
            "app.services.adaptive_rag_service.retrieve_documents_node",
            retrieve,
        ), patch(
            "app.services.adaptive_rag_service.grade_documents_node",
            grade_docs,
        ), patch(
            "app.services.adaptive_rag_service.generate_answer_node",
            generate,
        ), patch(
            "app.services.adaptive_rag_service.grade_generation_node",
            grade_generation,
        ):
            events = [event async for event in adaptive_rag_service.run_adaptive_rag_stream("what is SQL and NoSQL", ["file-1"])]

        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result_reason"], adaptive_rag_service.PARTIAL_COVERAGE_RESULT_REASON)
        self.assertIn("do not provide enough reliable information about SQL", events[-1]["answer"])
