import unittest
from unittest.mock import AsyncMock, patch

from app.services.rag.retrieval import service as adaptive_retrieval_service
from tests.support import make_retrieval_doc as make_doc


class AdaptiveRetrievalResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_grading_exception_discards_unverified_chunks(self):
        with patch(
            "app.services.rag.retrieval.service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader unavailable")),
        ):
            graded = await adaptive_retrieval_service.grade_documents_node(
                {
                    "question": "what is SQL and NoSQL",
                    "candidate_documents": [
                        {
                            **make_doc("SQL definition", chunk_id="sql-1"),
                            "retrieved_for_concepts": ["SQL", "GraphQL"],
                        }
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
        self.assertTrue(graded["grading_failed"])

    async def test_multi_concept_retrieval_does_not_end_with_all_concepts_missing_when_grader_fails(self):
        sql_doc = make_doc("SQL definition", chunk_id="sql-1", score=0.4)
        nosql_doc = make_doc("NoSQL definition", chunk_id="nosql-1", score=0.3)

        async def vector_side_effect(query, selected_file_ids, *, k, log_prefix):
            del selected_file_ids, k, log_prefix
            if query == "definition of SQL":
                return ([sql_doc], "primary")
            if query == "definition of NoSQL":
                return ([nosql_doc], "primary")
            if query == "what is SQL and NoSQL":
                return ([], "primary")
            raise AssertionError(query)

        def fulltext_side_effect(query, selected_file_ids, retrieval_k):
            del selected_file_ids, retrieval_k
            if query in {"definition of SQL", "definition of NoSQL", "what is SQL and NoSQL"}:
                return []
            raise AssertionError(query)

        with patch(
            "app.services.rag.retrieval.service.retrieve_vector_context",
            AsyncMock(side_effect=vector_side_effect),
        ), patch(
            "app.services.rag.retrieval.service.pg_service.retrieve_context_by_keywords",
            side_effect=fulltext_side_effect,
        ), patch(
            "app.services.rag.retrieval.service.classify_query_intent",
            AsyncMock(
                return_value={
                    "mode": "multi",
                    "intent_type": "definition_multi",
                    "required_concepts": ["SQL", "NoSQL"],
                    "subqueries": [
                        {
                            "label": "SQL",
                            "query": "definition of SQL",
                            "concept": "SQL",
                            "query_kind": "concept_definition",
                        },
                        {
                            "label": "NoSQL",
                            "query": "definition of NoSQL",
                            "concept": "NoSQL",
                            "query_kind": "concept_definition",
                        },
                    ],
                    "search_queries": [
                        {
                            "label": "SQL",
                            "query": "definition of SQL",
                            "concept": "SQL",
                            "query_kind": "concept_definition",
                        },
                        {
                            "label": "NoSQL",
                            "query": "definition of NoSQL",
                            "concept": "NoSQL",
                            "query_kind": "concept_definition",
                        },
                        {
                            "label": "combined definition",
                            "query": "what is SQL and NoSQL",
                            "concept": None,
                            "query_kind": "combined_definition",
                        },
                    ],
                }
            ),
        ), patch(
            "app.services.rag.retrieval.service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader unavailable")),
        ):
            result = await adaptive_retrieval_service.run_adaptive_retrieval(
                "what is SQL and NoSQL",
                ["file-1"],
            )

        self.assertEqual(result["fallback_reason"], adaptive_retrieval_service.NO_RELEVANT_DOCUMENTS_FALLBACK_REASON)
        self.assertEqual(result["covered_concepts"], [])
        self.assertEqual(result["missing_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(result["documents"], [])

    async def test_missing_concept_targeted_retry_retrieves_only_missing_concept_and_merges_grades(self):
        sql_doc = make_doc("SQL definition", chunk_id="sql-1")
        nosql_doc = make_doc("NoSQL definition", chunk_id="nosql-1")
        vector_queries = []

        async def vector_side_effect(query, selected_file_ids, *, k, log_prefix):
            del selected_file_ids, k, log_prefix
            vector_queries.append(query)
            if query == "definition of SQL":
                return ([sql_doc], "primary")
            if query == "definition of NoSQL":
                return ([], "primary")
            if query == "NoSQL what is SQL and NoSQL":
                return ([nosql_doc], "primary")
            raise AssertionError(query)

        def fulltext_side_effect(query, selected_file_ids, retrieval_k):
            del query, selected_file_ids, retrieval_k
            return []

        intent = {
            "mode": "multi",
            "intent_type": "comparison",
            "required_concepts": ["SQL", "NoSQL"],
            "subqueries": [],
            "search_queries": [
                {
                    "label": "SQL",
                    "query": "definition of SQL",
                    "concept": "SQL",
                    "query_kind": "concept_definition",
                },
                {
                    "label": "NoSQL",
                    "query": "definition of NoSQL",
                    "concept": "NoSQL",
                    "query_kind": "concept_definition",
                },
            ],
        }

        async def grade_side_effect(prompt, schema, *, operation_name, **kwargs):
            del schema, operation_name, kwargs
            if "[Chunk nosql-1]" in prompt:
                return {
                    "grades": [
                        {
                            "chunk_id": "nosql-1",
                            "relevance_score": 0.9,
                            "covered_concepts": ["NoSQL"],
                            "reason": "direct NoSQL support",
                        }
                    ]
                }
            return {
                "grades": [
                    {
                        "chunk_id": "sql-1",
                        "relevance_score": 0.9,
                        "covered_concepts": ["SQL"],
                        "reason": "direct SQL support",
                    }
                ]
            }

        with patch(
            "app.services.rag.retrieval.service.retrieve_vector_context",
            AsyncMock(side_effect=vector_side_effect),
        ), patch(
            "app.services.rag.retrieval.service.pg_service.retrieve_context_by_keywords",
            side_effect=fulltext_side_effect,
        ), patch(
            "app.services.rag.retrieval.service.classify_query_intent",
            AsyncMock(return_value=intent),
        ), patch(
            "app.services.rag.retrieval.service.generate_structured_json",
            AsyncMock(side_effect=grade_side_effect),
        ):
            result = await adaptive_retrieval_service.run_adaptive_retrieval(
                "what is SQL and NoSQL",
                ["file-1"],
            )

        self.assertEqual(result["fallback_reason"], None)
        self.assertEqual(result["covered_concepts"], ["SQL", "NoSQL"])
        self.assertEqual([doc["chunkId"] for doc in result["documents"]], ["sql-1", "nosql-1"])
        self.assertIn("NoSQL what is SQL and NoSQL", vector_queries)
        self.assertNotIn("SQL what is SQL and NoSQL", vector_queries)
