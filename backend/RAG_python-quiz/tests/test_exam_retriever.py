import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes import retriever


def make_retryable_error():
    from app.utils.ingest_errors import EmbeddingProviderError

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
    async def test_retriever_helpers_cover_duplicate_warning_and_search_query_variants(self):
        warnings = [retriever.DEGRADED_RETRIEVAL_WARNING]
        self.assertIs(retriever._append_warning(warnings, retriever.DEGRADED_RETRIEVAL_WARNING), warnings)

        with self.assertRaises(ValueError):
            await retriever.retriever_node(base_state(file_ids=[]))

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([make_chunk("topic chunk")], "primary")),
        ) as retrieve_vector_context:
            await retriever.retriever_node(base_state(topic="CAP theorem"))
        self.assertIn("CAP theorem difficult level exam questions", retrieve_vector_context.await_args.args[0])

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([make_chunk("research chunk")], "primary")),
        ) as retrieve_vector_context:
            await retriever.retriever_node(base_state(research_goal="transaction blocking"))
        self.assertIn("transaction blocking difficult level details", retrieve_vector_context.await_args.args[0])

    async def test_primary_retrieval_builds_chunk_context(self):
        chunk = make_chunk("primary chunk")

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([chunk], "primary")),
        ) as retrieve_vector_context:
            result = await retriever.retriever_node(base_state())

        retrieve_vector_context.assert_awaited_once_with(
            "key concepts main topics important definitions difficult",
            ["file-1"],
            k=15,
            log_prefix="Retriever",
        )
        self.assertEqual(result["context_chunks"], [chunk])
        self.assertIn("primary chunk", result["context"])
        self.assertEqual(result["warnings"], [])

    async def test_fallback_retrieval_still_uses_chunk_results_without_warning(self):
        chunk = make_chunk("fallback chunk")

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([chunk], "fallback")),
        ):
            result = await retriever.retriever_node(base_state())

        self.assertEqual(result["context_chunks"], [chunk])
        self.assertIn("fallback chunk", result["context"])
        self.assertEqual(result["warnings"], [])

    async def test_fallback_mode_after_primary_unavailable_uses_chunk_results_without_warning(self):
        chunk = make_chunk("fallback after no endpoints")

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([chunk], "fallback")),
        ):
            result = await retriever.retriever_node(base_state())

        self.assertEqual(result["context_chunks"], [chunk])
        self.assertIn("fallback after no endpoints", result["context"])
        self.assertEqual(result["warnings"], [])

    async def test_both_embedding_models_fail_without_existing_chunks_uses_full_text(self):
        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
        ), patch(
            "app.agents.nodes.retriever.pg_service.get_files_text_content",
            return_value="FULL TEXT",
        ) as get_files_text_content:
            result = await retriever.retriever_node(base_state())

        get_files_text_content.assert_called_once_with(["file-1"])
        self.assertEqual(result["context"], "FULL TEXT")
        self.assertEqual(result["context_chunks"], [])
        self.assertIn(retriever.DEGRADED_RETRIEVAL_WARNING, result["warnings"])
        self.assertEqual(result["search_iterations"], 0)
        self.assertIsNone(result["research_goal"])

    async def test_both_embedding_models_fail_with_existing_chunks_preserves_existing_context(self):
        existing_chunk = make_chunk("existing chunk", page=2)

        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(side_effect=make_retryable_error()),
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
        self.assertIn(retriever.DEGRADED_RETRIEVAL_WARNING, result["warnings"])
        self.assertEqual(result["search_iterations"], 2)
        self.assertIsNone(result["research_goal"])

    async def test_non_retryable_error_still_raises(self):
        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(side_effect=ValueError("bad input")),
        ):
            with self.assertRaises(ValueError):
                await retriever.retriever_node(base_state())

    async def test_empty_and_low_scoring_results_cover_remaining_paths(self):
        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([], "primary")),
        ), patch(
            "app.agents.nodes.retriever.pg_service.get_files_text_content",
            return_value="FULL TEXT",
        ):
            result = await retriever.retriever_node(base_state())
        self.assertEqual(result["context"], "FULL TEXT")

        low_score_chunk = make_chunk("fallback chunk", score=0.95)
        with patch(
            "app.agents.nodes.retriever.retrieve_vector_context",
            AsyncMock(return_value=([low_score_chunk], "primary")),
        ):
            result = await retriever.retriever_node(base_state())
        self.assertEqual(result["context_chunks"], [low_score_chunk])
