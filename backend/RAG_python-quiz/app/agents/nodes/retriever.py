"""
Retriever node for exam-generation RAG context gathering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.logger import get_logger
from app.services import pg_service
from app.services.vector_query_service import is_retryable_embedding_error, retrieve_vector_context

logger = get_logger(__name__)

DEFAULT_TOP_K = 15
MIN_SCORE_THRESHOLD = 0.3
MAX_TOTAL_CHUNKS = 30
DEGRADED_RETRIEVAL_WARNING = (
    "Vector retrieval was unavailable during exam generation; "
    "the system continued with degraded document context."
)


def _next_search_iteration(search_iterations: int, research_goal: str | None) -> int:
    return search_iterations + 1 if research_goal else 0


def _build_context_from_chunks(chunks: List[Dict[str, Any]]) -> str:
    context_parts = []
    for chunk in chunks:
        source = chunk.get("source", "Unknown source")
        page = chunk.get("page", "?")
        text = chunk.get("text", "")
        context_parts.append(f"[Source: {source}, Page: {page}]\n{text}")
    return "\n\n---\n\n".join(context_parts)


def _append_warning(warnings: List[str], message: str) -> List[str]:
    if message in warnings:
        return warnings
    return warnings + [message]


async def retriever_node(state: Dict[str, Any]) -> Dict[str, Any]:
    file_ids = state.get("file_ids", [])
    topic = state.get("topic", "")
    difficulty = state.get("difficulty", "medium")
    num_questions = state.get("num_questions", 10)
    research_goal = state.get("research_goal")
    search_iterations = state.get("search_iterations", 0)
    existing_chunks = state.get("context_chunks", []) or []
    warnings = state.get("warnings", []) or []

    logger.info("[Retriever] Starting retrieval - files=%s iteration=%s", len(file_ids), search_iterations)

    if not file_ids:
        raise ValueError("At least one file id is required for exam retrieval")

    top_k = max(DEFAULT_TOP_K, num_questions * 2)

    if research_goal:
        logger.info("[Retriever] Running follow-up research query: %s", research_goal)
        search_query = f"{research_goal} {difficulty} level details"
    elif topic:
        search_query = f"{topic} {difficulty} level exam questions"
    else:
        search_query = f"key concepts main topics important definitions {difficulty}"

    logger.info("[Retriever] Generating query vector: %s...", search_query[:50])

    try:
        chunks, retrieval_mode = await retrieve_vector_context(
            search_query,
            file_ids,
            k=top_k,
            log_prefix="Retriever",
        )
        logger.info(
            "[Retriever] Vector retrieval completed - mode=%s top_k=%s results=%s",
            retrieval_mode,
            top_k,
            len(chunks),
        )
    except Exception as err:
        if not is_retryable_embedding_error(err):
            raise

        logger.warning("[Retriever] Both embedding models unavailable; degrading retrieval: %s", err)
        degraded_warnings = _append_warning(warnings, DEGRADED_RETRIEVAL_WARNING)
        next_iteration = _next_search_iteration(search_iterations, research_goal)

        if existing_chunks:
            return {
                **state,
                "context": _build_context_from_chunks(existing_chunks),
                "context_chunks": existing_chunks,
                "warnings": degraded_warnings,
                "search_iterations": next_iteration,
                "research_goal": None,
            }

        full_text = await asyncio.to_thread(pg_service.get_files_text_content, file_ids)
        return {
            **state,
            "context": full_text,
            "context_chunks": [],
            "warnings": degraded_warnings,
            "search_iterations": next_iteration,
            "research_goal": None,
        }

    if not chunks and not existing_chunks:
        logger.warning("[Retriever] No vector matches found; falling back to selected files full text")
        full_text = await asyncio.to_thread(pg_service.get_files_text_content, file_ids)
        return {
            **state,
            "context": full_text,
            "context_chunks": [],
            "search_iterations": _next_search_iteration(search_iterations, research_goal),
            "research_goal": None,
        }

    filtered_chunks = [
        chunk
        for chunk in chunks
        if chunk.get("score") is None or chunk.get("score", 1) < (1 - MIN_SCORE_THRESHOLD)
    ]
    if not filtered_chunks and chunks:
        filtered_chunks = chunks[: top_k // 2]

    existing_contents = {chunk.get("text", "").strip() for chunk in existing_chunks}
    unique_new_chunks = []
    for chunk in filtered_chunks:
        text = chunk.get("text", "").strip()
        if text and text not in existing_contents:
            unique_new_chunks.append(chunk)
            existing_contents.add(text)

    logger.info("[Retriever] Added %s new unique chunks", len(unique_new_chunks))

    final_chunks = (unique_new_chunks + existing_chunks)[:MAX_TOTAL_CHUNKS]
    logger.info("[Retriever] Final context chunks=%s max=%s", len(final_chunks), MAX_TOTAL_CHUNKS)

    return {
        **state,
        "context": _build_context_from_chunks(final_chunks),
        "context_chunks": final_chunks,
        "search_iterations": _next_search_iteration(search_iterations, research_goal),
        "research_goal": None,
    }
