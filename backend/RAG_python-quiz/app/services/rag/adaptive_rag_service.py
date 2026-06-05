from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, TypedDict

from app.logger import get_logger
from app.services.ai.llm.structured_json import generate_structured_json
from app.services.rag import (
    adaptive_rag_answer,
    adaptive_rag_events,
    adaptive_rag_generation_grading,
    adaptive_rag_routing,
    adaptive_rag_workflow,
    adaptive_retrieval_service,
    citation_evidence_service,
)
from app.services.rag.rag_shared import safe_emit as _safe_emit

logger = get_logger(__name__)

NO_DOCUMENTS_ANSWER = "Sorry, no relevant information was found in the specified documents."
OUT_OF_SCOPE_ANSWER = "Sorry, this question cannot be answered reliably from the selected documents."
UNSUPPORTED_RESULT_REASON = "unsupported_question"
NO_DOCUMENTS_RESULT_REASON = "no_relevant_documents"
UNRELIABLE_RESULT_REASON = "unreliable_generation"
PARTIAL_COVERAGE_RESULT_REASON = "partial_coverage"
MAX_DOCS_TO_GRADE = 8
MAX_REWRITE_ATTEMPTS = adaptive_retrieval_service.MAX_REWRITE_ATTEMPTS
MAX_GENERATION_RETRIES = 1
RETRIEVAL_K = adaptive_retrieval_service.RETRIEVAL_K
MAX_DOC_PREVIEW_CHARS = adaptive_retrieval_service.MAX_DOC_PREVIEW_CHARS


class AdaptiveRAGState(TypedDict, total=False):
    question: str
    original_question: str
    selected_file_ids: List[str]
    current_query: str
    route_decision: str
    rewrite_count: int
    generation_retry_count: int
    candidate_documents: List[Dict[str, Any]]
    filtered_documents: List[Dict[str, Any]]
    query_intent: Dict[str, Any]
    covered_concepts: List[str]
    missing_concepts: List[str]
    answer: str
    citations: List[Dict[str, Any]]
    answer_with_citations: List[Dict[str, Any]]
    raw_sources: List[Dict[str, Any]]
    evidence_nodes: List[Dict[str, Any]]
    result_reason: str


EventCallback = Callable[[str, Any, str], Awaitable[None]]

_utc_now = adaptive_rag_events.utc_now
_make_event = adaptive_rag_events.make_event
_build_result_payload = adaptive_rag_events.build_result_payload
_initial_rag_state = adaptive_rag_events.initial_rag_state
_make_queue_emit = adaptive_rag_events.make_queue_emit
_flush_events = adaptive_rag_events.flush_events


async def route_question_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_rag_routing.route_question_node(
        state,
        emit,
        generate_structured_json=generate_structured_json,
        safe_emit=_safe_emit,
        logger=logger,
    )


async def retrieve_documents_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_retrieval_service.retrieve_documents_node(
        state,
        emit,
        retrieval_k=RETRIEVAL_K,
        max_docs_to_grade=MAX_DOCS_TO_GRADE,
        log_prefix="AdaptiveRAG",
    )


async def grade_documents_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_retrieval_service.grade_documents_node(
        state,
        emit,
        log_prefix="AdaptiveRAG",
    )


async def rewrite_query_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_retrieval_service.rewrite_query_node(
        state,
        emit,
        max_rewrite_attempts=MAX_REWRITE_ATTEMPTS,
        log_prefix="AdaptiveRAG",
    )


async def generate_answer_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_rag_answer.generate_answer_node(
        state,
        emit,
        generate_citation_evidence=citation_evidence_service.generate_citation_evidence,
        safe_emit=_safe_emit,
        partial_coverage_reason=PARTIAL_COVERAGE_RESULT_REASON,
        logger=logger,
    )


async def grade_generation_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    return await adaptive_rag_generation_grading.grade_generation_node(
        state,
        emit,
        generate_structured_json=generate_structured_json,
        safe_emit=_safe_emit,
        unreliable_reason=UNRELIABLE_RESULT_REASON,
        partial_coverage_reason=PARTIAL_COVERAGE_RESULT_REASON,
        max_doc_preview_chars=MAX_DOC_PREVIEW_CHARS,
        logger=logger,
    )


async def _run_rag_workflow(
    question: str,
    state: AdaptiveRAGState,
    emit: EventCallback,
    events: asyncio.Queue[Dict[str, Any]],
) -> AsyncGenerator[Dict[str, Any], None]:
    async for event in adaptive_rag_workflow.run_rag_workflow(
        question,
        state,
        emit,
        events,
        route_question_node=route_question_node,
        retrieve_documents_node=retrieve_documents_node,
        grade_documents_node=grade_documents_node,
        generate_answer_node=generate_answer_node,
        grade_generation_node=grade_generation_node,
        rewrite_query_node=rewrite_query_node,
        flush_events=_flush_events,
        make_event=_make_event,
        build_result_payload=_build_result_payload,
        no_documents_answer=NO_DOCUMENTS_ANSWER,
        out_of_scope_answer=OUT_OF_SCOPE_ANSWER,
        unsupported_result_reason=UNSUPPORTED_RESULT_REASON,
        no_documents_result_reason=NO_DOCUMENTS_RESULT_REASON,
        unreliable_result_reason=UNRELIABLE_RESULT_REASON,
        max_generation_retries=MAX_GENERATION_RETRIES,
        max_rewrite_attempts=MAX_REWRITE_ATTEMPTS,
        logger=logger,
    ):
        yield event


async def run_adaptive_rag_stream(question: str, selected_file_ids: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
    logger.info("[AdaptiveRAG] stream_start question=%r selected_file_ids=%s", question[:160], selected_file_ids)
    yield _make_event("Starting retrieval...", {"question": question}, event_type="retrieval")

    if not selected_file_ids:
        logger.warning("[AdaptiveRAG] stream_end empty_selection")
        yield _make_event("Please select at least one document for retrieval.", event_type="retrieval")
        return

    events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    state = _initial_rag_state(question, selected_file_ids)
    emit = _make_queue_emit(events)
    async for event in _run_rag_workflow(question, state, emit, events):
        yield event
