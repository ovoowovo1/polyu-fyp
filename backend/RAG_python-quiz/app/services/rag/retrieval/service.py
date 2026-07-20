from __future__ import annotations

from typing import Any, Dict, List

from app.logger import get_logger
from app.services.ai.llm.structured_json import generate_structured_json
from app.services.pg import pg_retrieval_service as pg_service
from app.services.rag.retrieval import grading as adaptive_grading
from app.services.rag.retrieval import intent as retrieval_intent
from app.services.rag.retrieval import rewrite as adaptive_rewrite
from app.services.rag.retrieval import search as adaptive_search
from app.services.rag.retrieval import workflow as adaptive_retrieval_workflow
from app.services.rag.retrieval.types import AdaptiveRetrievalResult, AdaptiveRetrievalState, EventCallback
from app.services.rag.retrieval.vector import is_retryable_embedding_error, retrieve_vector_context

logger = get_logger(__name__)

MAX_DOCS_TO_GRADE = 8
MAX_REWRITE_ATTEMPTS = 1
RETRIEVAL_K = 20
NO_RELEVANT_DOCUMENTS_FALLBACK_REASON = "no_relevant_documents"
EMPTY_SELECTION_FALLBACK_REASON = "empty_selection"

# Compatibility aliases used by existing unit tests and older imports.
RRF_K = adaptive_search.RRF_K
MAX_DOC_PREVIEW_CHARS = adaptive_grading.MAX_DOC_PREVIEW_CHARS
DOCUMENT_GRADING_CONCURRENCY = adaptive_grading.DOCUMENT_GRADING_CONCURRENCY
SUBQUERY_RETRIEVAL_CONCURRENCY = adaptive_search.SUBQUERY_RETRIEVAL_CONCURRENCY
RESERVED_CANDIDATES_PER_SUBQUERY = adaptive_search.RESERVED_CANDIDATES_PER_SUBQUERY
_normalize_doc = adaptive_search.normalize_retrieval_doc
_reciprocal_rank_fusion = adaptive_search.fuse_ranked_results
_merge_candidate_documents = adaptive_search.merge_retrieval_candidates
_build_retrieval_mode_summary = adaptive_search.build_retrieval_mode_summary
_build_document_grading_schema = adaptive_grading.build_document_grading_schema
_build_document_grading_prompt = adaptive_grading.build_document_grading_prompt
_collect_grading_outputs = adaptive_grading.collect_grading_outputs


async def classify_query_intent(question: str) -> retrieval_intent.QueryIntent:
    return await retrieval_intent.classify_query_intent(
        question,
        generate_structured_json_func=generate_structured_json,
    )


async def retrieve_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    retrieval_k: int = RETRIEVAL_K,
    max_docs_to_grade: int = MAX_DOCS_TO_GRADE,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    return await adaptive_search.retrieve_documents_node(
        state,
        emit,
        retrieval_k=retrieval_k,
        max_docs_to_grade=max_docs_to_grade,
        log_prefix=log_prefix,
        retrieve_vector_context_func=retrieve_vector_context,
        retrieve_context_by_keywords_func=pg_service.retrieve_context_by_keywords,
        is_retryable_embedding_error_func=is_retryable_embedding_error,
        classify_query_intent_func=classify_query_intent,
    )


async def grade_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    return await adaptive_grading.grade_documents_node(
        state,
        emit,
        log_prefix=log_prefix,
        generate_structured_json_func=generate_structured_json,
    )


async def rewrite_query_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    max_rewrite_attempts: int = MAX_REWRITE_ATTEMPTS,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    return await adaptive_rewrite.rewrite_query_node(
        state,
        emit,
        max_rewrite_attempts=max_rewrite_attempts,
        log_prefix=log_prefix,
        generate_structured_json_func=generate_structured_json,
        classify_query_intent_func=classify_query_intent,
    )


async def retry_missing_concepts_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    return await adaptive_search.retry_missing_concepts_node(
        state,
        emit,
        retrieval_k=RETRIEVAL_K,
        max_docs_to_grade=MAX_DOCS_TO_GRADE,
        log_prefix=log_prefix,
        retrieve_vector_context_func=retrieve_vector_context,
        retrieve_context_by_keywords_func=pg_service.retrieve_context_by_keywords,
        is_retryable_embedding_error_func=is_retryable_embedding_error,
    )


async def run_adaptive_retrieval(
    question: str,
    selected_file_ids: List[str],
    *,
    emit: EventCallback | None = None,
    retrieval_k: int = RETRIEVAL_K,
    max_docs_to_grade: int = MAX_DOCS_TO_GRADE,
    max_rewrite_attempts: int = MAX_REWRITE_ATTEMPTS,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalResult:
    emit_callback = emit or adaptive_retrieval_workflow.noop_emit
    logger.info(
        "[%s] run_start question=%r selected_files=%s retrieval_k=%s max_docs_to_grade=%s",
        log_prefix,
        question[:160],
        len(selected_file_ids),
        retrieval_k,
        max_docs_to_grade,
    )

    initial_intent = await classify_query_intent(question.strip())

    if not selected_file_ids:
        logger.warning("[%s] run_end empty_selection", log_prefix)
        return adaptive_retrieval_workflow.build_empty_selection_result(
            question,
            initial_intent,
            EMPTY_SELECTION_FALLBACK_REASON,
        )

    state = adaptive_retrieval_workflow.build_initial_state(question, selected_file_ids, initial_intent)
    return await adaptive_retrieval_workflow.run_retrieval_loop(
        state,
        question,
        initial_intent,
        emit_callback,
        retrieval_k=retrieval_k,
        max_docs_to_grade=max_docs_to_grade,
        max_rewrite_attempts=max_rewrite_attempts,
        log_prefix=log_prefix,
        no_relevant_documents_fallback_reason=NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
        logger=logger,
        retrieve_documents_node=retrieve_documents_node,
        grade_documents_node=grade_documents_node,
        retry_missing_concepts_node=retry_missing_concepts_node,
        max_missing_concept_retries=1,
        rewrite_query_node=rewrite_query_node,
    )


def _result_from_state(
    state: AdaptiveRetrievalState,
    question: str,
    initial_intent: Dict[str, Any],
    *,
    fallback_reason: str | None,
) -> AdaptiveRetrievalResult:
    return adaptive_retrieval_workflow.result_from_state(
        state,
        question,
        initial_intent,
        fallback_reason=fallback_reason,
    )
