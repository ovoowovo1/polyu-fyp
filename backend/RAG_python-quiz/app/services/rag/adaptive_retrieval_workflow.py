from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from app.services.rag.adaptive_types import AdaptiveRetrievalResult, AdaptiveRetrievalState

EmitCallback = Callable[[str, Any, str], Awaitable[None]]
NodeFunc = Callable[..., Awaitable[AdaptiveRetrievalState]]


async def noop_emit(message: str, data: Any = None, event_type: str = "retrieval") -> None:
    return None


def empty_retrieval_mode_summary() -> Dict[str, Any]:
    return {
        "vector_hits": 0,
        "fulltext_hits": 0,
        "vector_failed": False,
        "fulltext_failed": False,
        "vector_retrieval_degraded": False,
        "subquery_summaries": [],
    }


def build_empty_selection_result(
    question: str,
    initial_intent: Dict[str, Any],
    fallback_reason: str,
) -> AdaptiveRetrievalResult:
    return {
        "documents": [],
        "candidate_documents": [],
        "rewrite_count": 0,
        "current_query": question.strip(),
        "fallback_reason": fallback_reason,
        "retrieval_mode_summary": empty_retrieval_mode_summary(),
        "vector_retrieval_degraded": False,
        "query_intent": initial_intent,
        "covered_concepts": [],
        "missing_concepts": initial_intent["required_concepts"],
    }


def build_initial_state(
    question: str,
    selected_file_ids: List[str],
    initial_intent: Dict[str, Any],
) -> AdaptiveRetrievalState:
    stripped_question = question.strip()
    return {
        "question": stripped_question,
        "original_question": stripped_question,
        "selected_file_ids": list(selected_file_ids),
        "current_query": stripped_question,
        "rewrite_count": 0,
        "candidate_documents": [],
        "filtered_documents": [],
        "fallback_reason": None,
        "query_intent": initial_intent,
        "covered_concepts": [],
        "missing_concepts": [],
        "retrieval_mode_summary": empty_retrieval_mode_summary(),
        "vector_retrieval_degraded": False,
    }


def result_from_state(
    state: AdaptiveRetrievalState,
    question: str,
    initial_intent: Dict[str, Any],
    *,
    fallback_reason: str | None,
) -> AdaptiveRetrievalResult:
    return {
        "documents": state.get("filtered_documents", []),
        "candidate_documents": state.get("candidate_documents", []),
        "rewrite_count": state.get("rewrite_count", 0),
        "current_query": state.get("current_query", question.strip()),
        "fallback_reason": fallback_reason,
        "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
        "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
        "query_intent": state.get("query_intent", initial_intent),
        "covered_concepts": state.get("covered_concepts", []),
        "missing_concepts": state.get("missing_concepts", []),
    }


async def run_retrieval_loop(
    state: AdaptiveRetrievalState,
    question: str,
    initial_intent: Dict[str, Any],
    emit_callback: EmitCallback,
    *,
    retrieval_k: int,
    max_docs_to_grade: int,
    max_rewrite_attempts: int,
    log_prefix: str,
    no_relevant_documents_fallback_reason: str,
    logger,
    retrieve_documents_node: NodeFunc,
    grade_documents_node: NodeFunc,
    rewrite_query_node: NodeFunc,
) -> AdaptiveRetrievalResult:
    while True:
        state = await retrieve_documents_node(
            state,
            emit_callback,
            retrieval_k=retrieval_k,
            max_docs_to_grade=max_docs_to_grade,
            log_prefix=log_prefix,
        )
        state = await grade_documents_node(
            state,
            emit_callback,
            log_prefix=log_prefix,
        )

        if state.get("filtered_documents"):
            logger.info(
                "[%s] run_end success kept_chunks=%s rewrite_count=%s covered_concepts=%s missing_concepts=%s",
                log_prefix,
                len(state.get("filtered_documents", [])),
                state.get("rewrite_count", 0),
                state.get("covered_concepts", []),
                state.get("missing_concepts", []),
            )
            return result_from_state(state, question, initial_intent, fallback_reason=None)

        if state.get("rewrite_count", 0) >= max_rewrite_attempts:
            logger.warning(
                "[%s] run_end no_documents rewrite_count=%s fallback_reason=%s missing_concepts=%s",
                log_prefix,
                state.get("rewrite_count", 0),
                no_relevant_documents_fallback_reason,
                state.get("missing_concepts", []),
            )
            return result_from_state(
                state,
                question,
                initial_intent,
                fallback_reason=no_relevant_documents_fallback_reason,
            )

        state = await rewrite_query_node(
            state,
            emit_callback,
            max_rewrite_attempts=max_rewrite_attempts,
            log_prefix=log_prefix,
        )
