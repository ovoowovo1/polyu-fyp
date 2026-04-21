"""
Retriever node for exam-generation RAG context gathering.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.logger import get_logger
from app.services import pg_service
from app.services.adaptive_retrieval_service import (
    NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
    run_adaptive_retrieval,
)

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


def _build_search_query(topic: str, difficulty: str, research_goal: str | None) -> str:
    if research_goal:
        return f"{research_goal} {difficulty} level details"
    if topic:
        return f"{topic} {difficulty} level exam questions"
    return f"key concepts main topics important definitions {difficulty}"


async def retriever_node(state: Dict[str, Any]) -> Dict[str, Any]:
    file_ids = state.get("file_ids", [])
    topic = state.get("topic", "")
    difficulty = state.get("difficulty", "medium")
    num_questions = state.get("num_questions", 10)
    research_goal = state.get("research_goal")
    search_iterations = state.get("search_iterations", 0)
    existing_chunks = state.get("context_chunks", []) or []
    warnings = state.get("warnings", []) or []

    logger.info(
        "[Retriever] Starting retrieval - files=%s iteration=%s topic=%r research_goal=%r existing_chunks=%s",
        len(file_ids),
        search_iterations,
        topic[:120],
        (research_goal or "")[:120],
        len(existing_chunks),
    )

    if not file_ids:
        raise ValueError("At least one file id is required for exam retrieval")

    top_k = max(DEFAULT_TOP_K, num_questions * 2)
    search_query = _build_search_query(topic, difficulty, research_goal)
    logger.info("[Retriever] Adaptive retrieval query=%r top_k=%s", search_query[:160], top_k)

    retrieval_result = await run_adaptive_retrieval(
        search_query,
        file_ids,
        retrieval_k=top_k,
        max_docs_to_grade=min(MAX_TOTAL_CHUNKS, top_k),
        log_prefix="ExamRetriever",
    )
    filtered_chunks = retrieval_result.get("documents", [])
    warnings_out = warnings

    if retrieval_result.get("vector_retrieval_degraded"):
        warnings_out = _append_warning(warnings_out, DEGRADED_RETRIEVAL_WARNING)

    logger.info(
        "[Retriever] Adaptive retrieval completed - filtered=%s candidates=%s rewrite_count=%s fallback_reason=%r degraded=%s",
        len(filtered_chunks),
        len(retrieval_result.get("candidate_documents", [])),
        retrieval_result.get("rewrite_count", 0),
        retrieval_result.get("fallback_reason"),
        retrieval_result.get("vector_retrieval_degraded", False),
    )

    if not filtered_chunks and not existing_chunks:
        logger.warning(
            "[Retriever] No adaptive retrieval matches found; falling back to selected files full text reason=%r",
            retrieval_result.get("fallback_reason") or NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
        )
        full_text = await asyncio.to_thread(pg_service.get_files_text_content, file_ids)
        return {
            **state,
            "context": full_text,
            "context_chunks": [],
            "warnings": warnings_out,
            "search_iterations": _next_search_iteration(search_iterations, research_goal),
            "research_goal": None,
        }

    existing_contents = {chunk.get("text", "").strip() for chunk in existing_chunks}
    unique_new_chunks = []
    for chunk in filtered_chunks:
        text = chunk.get("text", "").strip()
        if text and text not in existing_contents:
            unique_new_chunks.append(chunk)
            existing_contents.add(text)

    logger.info(
        "[Retriever] Added %s new unique chunks; existing=%s final_before_cap=%s",
        len(unique_new_chunks),
        len(existing_chunks),
        len(unique_new_chunks) + len(existing_chunks),
    )

    final_chunks = (unique_new_chunks + existing_chunks)[:MAX_TOTAL_CHUNKS]
    logger.info("[Retriever] Final context chunks=%s max=%s", len(final_chunks), MAX_TOTAL_CHUNKS)

    return {
        **state,
        "context": _build_context_from_chunks(final_chunks),
        "context_chunks": final_chunks,
        "warnings": warnings_out,
        "search_iterations": _next_search_iteration(search_iterations, research_goal),
        "research_goal": None,
    }
