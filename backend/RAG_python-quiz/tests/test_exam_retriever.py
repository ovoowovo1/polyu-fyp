import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes import retriever


def make_chunk(text="chunk text", *, source="doc.pdf", page=1, score=0.1):
    return {
        "text": text,
        "source": source,
        "page": page,
        "score": score,
        "fileId": "file-1",
        "chunkId": f"chunk-{page}",
    }


def base_state(**overrides):
    state = {
        "file_ids": ["file-1"],
        "topic": "",
        "difficulty": "difficult",
        "num_questions": 3,
        "research_goal": None,
        "search_iterations": 0,
        "context_chunks": [],
        "warnings": [],
    }
    state.update(overrides)
    return state


class ExamRetrieverTests(unittest.IsolatedAsyncioTestCase):
    async def test_retriever_helpers_cover_warning_and_query_variants(self):
        warnings = [retriever.DEGRADED_RETRIEVAL_WARNING]
        self.assertIs(retriever._append_warning(warnings, retriever.DEGRADED_RETRIEVAL_WARNING), warnings)
        self.assertEqual(
            retriever._build_search_query("CAP theorem", "difficult", None),
            "CAP theorem difficult level exam questions",
        )
        self.assertEqual(
            retriever._build_search_query("", "difficult", "transaction blocking"),
            "transaction blocking difficult level details",
        )
        self.assertEqual(
            retriever._build_search_query("", "difficult", None),
            "key concepts main topics important definitions difficult",
        )

        with self.assertRaises(ValueError):
            await retriever.retriever_node(base_state(file_ids=[]))

    async def test_primary_adaptive_retrieval_builds_chunk_context(self):
        chunk = make_chunk("primary chunk")

        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(
                return_value={
                    "documents": [chunk],
                    "candidate_documents": [chunk],
                    "rewrite_count": 0,
                    "fallback_reason": None,
                    "vector_retrieval_degraded": False,
                }
            ),
        ) as run_adaptive_retrieval:
            result = await retriever.retriever_node(base_state())

        run_adaptive_retrieval.assert_awaited_once_with(
            "key concepts main topics important definitions difficult",
            ["file-1"],
            retrieval_k=15,
            max_docs_to_grade=15,
            log_prefix="ExamRetriever",
        )
        self.assertEqual(result["context_chunks"], [chunk])
        self.assertIn("primary chunk", result["context"])
        self.assertEqual(result["warnings"], [])

    async def test_research_goal_query_merges_unique_chunks_with_existing_context(self):
        existing_chunk = make_chunk("existing chunk", page=2)
        new_chunk = make_chunk("new chunk", page=3)
        duplicate_chunk = make_chunk("existing chunk", page=4)

        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(
                return_value={
                    "documents": [duplicate_chunk, new_chunk],
                    "candidate_documents": [duplicate_chunk, new_chunk],
                    "rewrite_count": 1,
                    "fallback_reason": None,
                    "vector_retrieval_degraded": False,
                }
            ),
        ) as run_adaptive_retrieval:
            result = await retriever.retriever_node(
                base_state(
                    research_goal="transaction blocking",
                    search_iterations=1,
                    context_chunks=[existing_chunk],
                )
            )

        self.assertIn("transaction blocking difficult level details", run_adaptive_retrieval.await_args.args[0])
        self.assertEqual(result["context_chunks"], [new_chunk, existing_chunk])
        self.assertEqual(result["search_iterations"], 2)
        self.assertIsNone(result["research_goal"])

    async def test_vector_degraded_warning_is_preserved(self):
        chunk = make_chunk("fallback chunk")

        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(
                return_value={
                    "documents": [chunk],
                    "candidate_documents": [chunk],
                    "rewrite_count": 0,
                    "fallback_reason": None,
                    "vector_retrieval_degraded": True,
                }
            ),
        ):
            result = await retriever.retriever_node(base_state())

        self.assertEqual(result["context_chunks"], [chunk])
        self.assertIn(retriever.DEGRADED_RETRIEVAL_WARNING, result["warnings"])

    async def test_empty_adaptive_results_without_existing_chunks_falls_back_to_full_text(self):
        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(
                return_value={
                    "documents": [],
                    "candidate_documents": [],
                    "rewrite_count": 1,
                    "fallback_reason": "no_relevant_documents",
                    "vector_retrieval_degraded": False,
                }
            ),
        ), patch(
            "app.agents.nodes.retriever.pg_service.get_files_text_content",
            return_value="FULL TEXT",
        ) as get_files_text_content:
            result = await retriever.retriever_node(base_state())

        get_files_text_content.assert_called_once_with(["file-1"])
        self.assertEqual(result["context"], "FULL TEXT")
        self.assertEqual(result["context_chunks"], [])
        self.assertEqual(result["search_iterations"], 0)
        self.assertIsNone(result["research_goal"])

    async def test_empty_adaptive_results_with_existing_chunks_preserves_existing_context(self):
        existing_chunk = make_chunk("existing chunk", page=2)

        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(
                return_value={
                    "documents": [],
                    "candidate_documents": [],
                    "rewrite_count": 1,
                    "fallback_reason": "no_relevant_documents",
                    "vector_retrieval_degraded": True,
                }
            ),
        ), patch(
            "app.agents.nodes.retriever.pg_service.get_files_text_content",
        ) as get_files_text_content:
            result = await retriever.retriever_node(
                base_state(
                    research_goal="missing topic",
                    search_iterations=1,
                    context_chunks=[existing_chunk],
                )
            )

        get_files_text_content.assert_not_called()
        self.assertEqual(result["context_chunks"], [existing_chunk])
        self.assertIn("existing chunk", result["context"])
        self.assertEqual(result["search_iterations"], 2)
        self.assertIn(retriever.DEGRADED_RETRIEVAL_WARNING, result["warnings"])

    async def test_non_retryable_service_error_still_raises(self):
        with patch(
            "app.agents.nodes.retriever.run_adaptive_retrieval",
            AsyncMock(side_effect=ValueError("bad input")),
        ):
            with self.assertRaises(ValueError):
                await retriever.retriever_node(base_state())
