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
    def test_analyze_query_intent_detects_definition_and_comparison_queries(self):
        normalized = adaptive_retrieval_service._normalize_doc(
            {
                "text": "chunk",
                "retrieved_for_concepts": [" SQL ", "", "SQL", "NoSQL"],
                "covered_concepts": [" sql "],
            }
        )
        self.assertEqual(normalized["retrieved_for_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(normalized["covered_concepts"], ["SQL"])
        self.assertEqual(adaptive_retrieval_service._unique_in_order([" SQL ", "", "SQL", "NoSQL"]), ["SQL", "NoSQL"])

        single = adaptive_retrieval_service.analyze_query_intent("What is CAP theorem?")
        self.assertEqual(single["mode"], "single")
        self.assertEqual(single["intent_type"], "single")
        self.assertEqual(single["required_concepts"], [])
        self.assertEqual(single["search_queries"][0]["query"], "What is CAP theorem?")

        multi = adaptive_retrieval_service.analyze_query_intent("what is SQL and Nosql")
        self.assertEqual(multi["mode"], "multi")
        self.assertEqual(multi["intent_type"], "definition_multi")
        self.assertEqual(multi["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(
            [query["query"] for query in multi["subqueries"]],
            ["definition of SQL database language", "definition of NoSQL database"],
        )

        comparison = adaptive_retrieval_service.analyze_query_intent("what is the different in SQL and NOsql")
        self.assertEqual(comparison["mode"], "multi")
        self.assertEqual(comparison["intent_type"], "comparison")
        self.assertEqual(comparison["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(comparison["search_queries"][0]["query"], "difference between SQL and NoSQL databases")

        versus = adaptive_retrieval_service.analyze_query_intent("SQL vs NoSQL")
        self.assertEqual(versus["intent_type"], "comparison")
        self.assertEqual(versus["required_concepts"], ["SQL", "NoSQL"])

        fallback = adaptive_retrieval_service.analyze_query_intent(
            "better query",
            fallback_required_concepts=["SQL", "NoSQL"],
            fallback_intent_type="comparison",
        )
        self.assertEqual(fallback["intent_type"], "comparison")
        self.assertEqual(fallback["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(adaptive_retrieval_service._canonicalize_known_concept("newsql"), "NewSQL")
        self.assertEqual(adaptive_retrieval_service._definition_query_for_concept("MongoDB"), "definition of MongoDB")
        self.assertEqual(
            adaptive_retrieval_service._comparison_query_for_concepts(["SQL", "NoSQL", "NewSQL"]),
            "comparison between SQL and NoSQL and NewSQL",
        )

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
        self.assertEqual(result["query_intent"]["mode"], "single")
        self.assertEqual(result["query_intent"]["intent_type"], "single")
        self.assertEqual(result["covered_concepts"], [])
        self.assertEqual(result["missing_concepts"], [])

    def test_merge_candidate_documents_tracks_retrieval_hints_only(self):
        merged = adaptive_retrieval_service._merge_candidate_documents(
            [
                {
                    "query_spec": {"label": "SQL", "query": "definition of SQL database language", "concept": "SQL", "query_kind": "concept_definition"},
                    "vector_results": [make_doc("sql vector", chunk_id="sql-1")],
                    "fulltext_results": [],
                    "fused": [make_doc("sql vector", chunk_id="sql-1", score=0.4)],
                },
                {
                    "query_spec": {"label": "NoSQL", "query": "definition of NoSQL database", "concept": "NoSQL", "query_kind": "concept_definition"},
                    "vector_results": [make_doc("nosql vector", chunk_id="nosql-1")],
                    "fulltext_results": [],
                    "fused": [make_doc("nosql vector", chunk_id="nosql-1", score=0.3)],
                },
            ],
            max_docs_to_grade=2,
        )

        self.assertEqual([doc["chunkId"] for doc in merged], ["sql-1", "nosql-1"])
        self.assertEqual(merged[0]["retrieved_for_concepts"], ["SQL"])
        self.assertEqual(merged[1]["retrieved_for_concepts"], ["NoSQL"])

    def test_merge_candidate_documents_skips_missing_and_duplicate_chunk_ids(self):
        with patch(
            "app.services.adaptive_retrieval_service._reciprocal_rank_fusion",
            return_value=[
                {"text": "ignored", "chunkId": None},
                make_doc("kept", chunk_id="chunk-1", score=0.4),
            ],
        ):
            merged = adaptive_retrieval_service._merge_candidate_documents(
                [
                    {
                        "query_spec": {"label": "original question", "query": "hello", "concept": None, "query_kind": "original"},
                        "vector_results": [{"text": "ignored", "chunkId": None}, make_doc("kept", chunk_id="chunk-1", score=0.4)],
                        "fulltext_results": [],
                        "fused": [{"text": "ignored", "chunkId": None}],
                    }
                ],
                max_docs_to_grade=2,
            )

        self.assertEqual([doc["chunkId"] for doc in merged], ["chunk-1"])

    def test_merge_candidate_documents_skips_duplicate_reserved_chunks(self):
        merged = adaptive_retrieval_service._merge_candidate_documents(
            [
                {
                    "query_spec": {"label": "SQL", "query": "definition of SQL database language", "concept": "SQL", "query_kind": "concept_definition"},
                    "vector_results": [make_doc("shared", chunk_id="shared-1")],
                    "fulltext_results": [],
                    "fused": [make_doc("shared", chunk_id="shared-1", score=0.4)],
                },
                {
                    "query_spec": {"label": "NoSQL", "query": "definition of NoSQL database", "concept": "NoSQL", "query_kind": "concept_definition"},
                    "vector_results": [make_doc("shared", chunk_id="shared-1")],
                    "fulltext_results": [],
                    "fused": [make_doc("shared", chunk_id="shared-1", score=0.4)],
                },
            ],
            max_docs_to_grade=3,
        )

        self.assertEqual([doc["chunkId"] for doc in merged], ["shared-1"])

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
        self.assertEqual(graded["filtered_documents"][0]["covered_concepts"], [])

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("rewrite down")),
        ):
            rewritten = await adaptive_retrieval_service.rewrite_query_node(
                {
                    "question": "what is the different in SQL and NOsql",
                    "original_question": "what is the different in SQL and NOsql",
                    "current_query": "what is the different in SQL and NOsql",
                    "query_intent": adaptive_retrieval_service.analyze_query_intent("what is the different in SQL and NOsql"),
                },
                emit,
                max_rewrite_attempts=2,
            )
        self.assertEqual(rewritten["current_query"], "what is the different in SQL and NOsql")
        self.assertEqual(rewritten["rewrite_count"], 1)
        self.assertEqual(rewritten["query_intent"]["intent_type"], "comparison")
        self.assertTrue(emitted)

    async def test_grade_documents_tracks_covered_and_missing_concepts(self):
        emitted = []

        async def emit(message, data=None, event_type="retrieval"):
            emitted.append((message, data, event_type))

        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(
                side_effect=[
                    {"relevant": "yes", "covered_concepts": ["SQL"], "reason": "sql definition"},
                    {"relevant": "yes", "covered_concepts": ["NoSQL"], "reason": "nosql definition"},
                ]
            ),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "what is SQL and NoSQL",
                    "candidate_documents": [
                        make_doc("SQL definition", chunk_id="sql-1"),
                        make_doc("NoSQL definition", chunk_id="nosql-1"),
                    ],
                    "query_intent": {
                        "mode": "multi",
                        "intent_type": "definition_multi",
                        "required_concepts": ["SQL", "NoSQL"],
                        "subqueries": [],
                        "search_queries": [],
                    },
                },
                emit,
            )

        self.assertEqual([doc["chunkId"] for doc in graded["filtered_documents"]], ["sql-1", "nosql-1"])
        self.assertEqual(graded["covered_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(graded["missing_concepts"], [])
        self.assertEqual(graded["filtered_documents"][0]["covered_concepts"], ["SQL"])
        self.assertTrue(emitted)

    async def test_retrieved_for_concepts_do_not_count_as_covered_or_force_keep(self):
        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(return_value={"relevant": "no", "covered_concepts": [], "reason": "incidental mention"}),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "what is SQL and NoSQL",
                    "candidate_documents": [
                        {**make_doc("incidental mention", chunk_id="chunk-1"), "retrieved_for_concepts": ["SQL"]}
                    ],
                    "query_intent": {
                        "mode": "multi",
                        "intent_type": "definition_multi",
                        "required_concepts": ["SQL", "NoSQL"],
                        "subqueries": [],
                        "search_queries": [],
                    },
                },
                AsyncMock(),
            )

        self.assertEqual(graded["filtered_documents"], [])
        self.assertEqual(graded["covered_concepts"], [])
        self.assertEqual(graded["missing_concepts"], ["SQL", "NoSQL"])

    async def test_grade_documents_runs_in_parallel_preserves_order_and_keeps_failed_chunks(self):
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
                {"question": "hello", "candidate_documents": docs},
                AsyncMock(),
            )

        self.assertEqual(call_order, ["chunk-3", "chunk-2", "chunk-1"])
        self.assertEqual([doc["chunkId"] for doc in graded["filtered_documents"]], ["chunk-1", "chunk-2"])
        self.assertEqual(graded["filtered_documents"][1]["covered_concepts"], [])

    async def test_grade_documents_supports_bounded_concurrency_branch(self):
        with patch.object(adaptive_retrieval_service, "DOCUMENT_GRADING_CONCURRENCY", 1), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(return_value={"relevant": "yes", "reason": "keep"}),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {"question": "hello", "candidate_documents": [make_doc("ctx", chunk_id="chunk-9")]},
                AsyncMock(),
            )

        self.assertEqual([doc["chunkId"] for doc in graded["filtered_documents"]], ["chunk-9"])

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

    async def test_run_adaptive_retrieval_merges_multi_concept_results_without_losing_sql_chunk(self):
        sql_doc = make_doc("SQL definition", chunk_id="sql-1", score=0.4)
        nosql_doc = make_doc("NoSQL definition", chunk_id="nosql-1", score=0.3)
        comparison_doc = make_doc("SQL and NoSQL comparison", chunk_id="cmp-1", score=0.2)

        async def vector_side_effect(query, selected_file_ids, *, k, log_prefix):
            del selected_file_ids, k, log_prefix
            if query == "definition of SQL database language":
                return ([sql_doc], "primary")
            if query == "definition of NoSQL database":
                return ([nosql_doc], "primary")
            if query == "what is SQL and NoSQL":
                return ([comparison_doc], "primary")
            raise AssertionError(query)

        def fulltext_side_effect(query, selected_file_ids, retrieval_k):
            del selected_file_ids, retrieval_k
            if query == "definition of SQL database language":
                return [sql_doc]
            if query == "definition of NoSQL database":
                return [nosql_doc]
            if query == "what is SQL and NoSQL":
                return [comparison_doc]
            raise AssertionError(query)

        async def structured_side_effect(prompt, schema, *, operation_name, **kwargs):
            del schema, kwargs
            if operation_name == "Adaptive RAG grade document":
                if "NoSQL definition" in prompt:
                    return {"relevant": "yes", "covered_concepts": ["NoSQL"], "reason": "nosql"}
                if "SQL definition" in prompt:
                    return {"relevant": "yes", "covered_concepts": ["SQL"], "reason": "sql"}
                return {"relevant": "no", "covered_concepts": [], "reason": "comparison not direct enough"}
            raise AssertionError(operation_name)

        with patch(
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(side_effect=vector_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            side_effect=fulltext_side_effect,
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=structured_side_effect),
        ):
            result = await collect_result(question="what is SQL and NoSQL")

        self.assertEqual(result["query_intent"]["mode"], "multi")
        self.assertEqual(result["query_intent"]["intent_type"], "definition_multi")
        self.assertEqual(result["covered_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(result["missing_concepts"], [])
        self.assertEqual([doc["chunkId"] for doc in result["documents"]], ["sql-1", "nosql-1"])
        self.assertEqual(result["documents"][0]["covered_concepts"], ["SQL"])
        self.assertEqual(result["documents"][1]["covered_concepts"], ["NoSQL"])
