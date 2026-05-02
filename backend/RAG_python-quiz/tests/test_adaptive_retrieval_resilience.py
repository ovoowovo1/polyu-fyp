import unittest
from unittest.mock import AsyncMock, patch

from app.services import adaptive_retrieval_service


def make_doc(text, *, chunk_id="chunk-1", source="doc.pdf", page=1, file_id="file-1", score=0.12):
    return {
        "text": text,
        "source": source,
        "page": page,
        "fileId": file_id,
        "chunkId": chunk_id,
        "score": score,
    }


class AdaptiveRetrievalResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_grading_exception_uses_retrieval_hints_for_covered_concepts(self):
        with patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
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

        self.assertEqual([doc["chunkId"] for doc in graded["filtered_documents"]], ["sql-1"])
        self.assertEqual(graded["filtered_documents"][0]["covered_concepts"], ["SQL"])
        self.assertEqual(graded["covered_concepts"], ["SQL"])
        self.assertEqual(graded["missing_concepts"], ["NoSQL"])

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
            "app.services.adaptive_retrieval_service._retrieve_vector_context",
            AsyncMock(side_effect=vector_side_effect),
        ), patch(
            "app.services.adaptive_retrieval_service.pg_service.retrieve_context_by_keywords",
            side_effect=fulltext_side_effect,
        ), patch(
            "app.services.adaptive_retrieval_service.generate_structured_json",
            AsyncMock(side_effect=RuntimeError("grader unavailable")),
        ):
            result = await adaptive_retrieval_service.run_adaptive_retrieval(
                "what is SQL and NoSQL",
                ["file-1"],
            )

        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["covered_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(result["missing_concepts"], [])
        self.assertEqual([doc["chunkId"] for doc in result["documents"]], ["sql-1", "nosql-1"])
        self.assertEqual(result["documents"][0]["covered_concepts"], ["SQL"])
        self.assertEqual(result["documents"][1]["covered_concepts"], ["NoSQL"])
