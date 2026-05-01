from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Sequence, TypedDict

from app.logger import get_logger
from app.services import adaptive_retrieval_service, citation_evidence_service, retrieval_intent
from app.services.ai_service import generate_structured_json
from app.services.rag_shared import build_raw_sources, normalize_doc, safe_emit

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
RRF_K = adaptive_retrieval_service.RRF_K
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_event(message: str, data: Any = None, event_type: str = "progress") -> Dict[str, Any]:
    return {
        "type": event_type,
        "message": message,
        "data": data,
        "timestamp": _utc_now(),
    }


def _normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_doc(doc)


def _reciprocal_rank_fusion(results_list: List[List[Dict[str, Any]]], k: int = RRF_K) -> List[Dict[str, Any]]:
    return adaptive_retrieval_service._reciprocal_rank_fusion(results_list, k=k)


async def _retrieve_vector_context(question: str, selected_file_ids: Sequence[str]) -> tuple[List[Dict[str, Any]], str]:
    return await adaptive_retrieval_service._retrieve_vector_context(
        question,
        selected_file_ids,
        k=RETRIEVAL_K,
        log_prefix="vector retrieval",
    )


def _format_docs_for_answer(documents: Sequence[Dict[str, Any]]) -> tuple[str, List[str], List[str]]:
    formatted_context: List[str] = []
    file_ids: List[str] = []
    chunk_ids: List[str] = []

    for idx, raw_doc in enumerate(documents, start=1):
        doc = normalize_doc(raw_doc)
        content = doc.get("text") or ""
        formatted_context.append(
            "\n".join(
                [
                    f"[Document {idx}]",
                    (
                        f'source_file: "{doc.get("source")}", '
                        f'page_number: "{doc.get("page")}", '
                        f'file_id: "{doc.get("fileId")}", '
                        f'file_chunk_id: "{doc.get("chunkId")}"'
                    ),
                    "Content:",
                    '"""',
                    content,
                    '"""',
                ]
            )
        )
        file_ids.append(doc.get("fileId"))
        chunk_ids.append(doc.get("chunkId"))

    return "\n\n".join(formatted_context), file_ids, chunk_ids


def _extract_answer_text(answer_with_citations: Any) -> str:
    if not isinstance(answer_with_citations, list):
        return ""

    parts: List[str] = []
    for block in answer_with_citations:
        for segment in block.get("content_segments", []):
            text = (segment.get("segment_text") or "").strip()
            if text:
                parts.append(text)

    return "\n\n".join(parts).strip()


def _sanitize_answer_with_citations(
    answer_with_citations: Any,
    allowed_chunk_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    allowed = {chunk_id for chunk_id in allowed_chunk_ids if chunk_id}
    sanitized: List[Dict[str, Any]] = []

    if not isinstance(answer_with_citations, list):
        return sanitized

    for block in answer_with_citations:
        segments = []
        for segment in block.get("content_segments", []):
            refs = []
            for ref in segment.get("source_references", []):
                chunk_id = ref.get("file_chunk_id")
                if chunk_id in allowed:
                    refs.append({"file_chunk_id": chunk_id})

            text = (segment.get("segment_text") or "").strip()
            if text and refs:
                segments.append(
                    {
                        "segment_text": text,
                        "source_references": refs,
                    }
                )

        if segments:
            sanitized.append({"content_segments": segments})

    return sanitized


def _build_result_payload(
    *,
    state: AdaptiveRAGState,
    question: str,
    answer: str,
    answer_with_citations: List[Dict[str, Any]],
    raw_sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    sources = build_raw_sources(raw_sources)

    return {
        "type": "result",
        "question": question.strip(),
        "answer": answer,
        "answer_with_citations": answer_with_citations,
        "raw_sources": sources,
        "result_reason": state.get("result_reason"),
        "timestamp": _utc_now(),
    }


async def _safe_emit(callback: EventCallback, message: str, data: Any = None, event_type: str = "retrieval") -> None:
    await safe_emit(callback, message, data, event_type)


async def route_question_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    logger.info(
        "[AdaptiveRAG] route_question start question=%r selected_files=%s",
        state["question"][:160],
        len(state.get("selected_file_ids", [])),
    )
    await _safe_emit(
        emit,
        "[router] assessing whether the question should be answered only from the selected documents.",
        event_type="router",
    )

    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["retrieve", "reject"]},
            "reason": {"type": "string"},
        },
        "required": ["decision", "reason"],
    }
    prompt = f"""
Decide whether the following user question is suitable for a document-grounded RAG answer.

Context:
- The system is only allowed to answer from the user's selected documents.
- It must not give an open-ended general-knowledge answer.
- Reject only when the question clearly requires external/current/personal information or is not plausibly answerable from study materials.
- If the question could reasonably be answered from course notes, lecture slides, reports, or selected files, choose retrieve.

Question:
{state["question"]}
"""

    try:
        result = await generate_structured_json(
            prompt,
            schema,
            operation_name="Adaptive RAG route question",
            temperature=0.0,
        )
        decision = result.get("decision", "retrieve")
    except Exception as err:
        logger.warning("[AdaptiveRAG] route_question fallback to retrieve: %s", err)
        decision = "retrieve"

    state["route_decision"] = decision
    logger.info("[AdaptiveRAG] route_question decision=%s", decision)
    return state


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
    documents = state.get("filtered_documents", [])
    logger.info(
        "[AdaptiveRAG] generate_answer start grounded_chunks=%s",
        len(documents),
    )

    await _safe_emit(
        emit,
        f"[generation] generating answer from {len(documents)} grounded chunks.",
        len(documents),
        "generation",
    )

    evidence_result = await citation_evidence_service.generate_citation_evidence(
        state["question"],
        documents,
        required_concepts=state.get("query_intent", {}).get("required_concepts", []),
        covered_concepts=state.get("covered_concepts", []),
        intent_type=state.get("query_intent", {}).get("intent_type", "single"),
    )
    answer_with_citations = evidence_result["answer_with_citations"]
    answer = evidence_result["answer_text"]

    state["answer"] = answer
    state["citations"] = evidence_result["citations"]
    state["answer_with_citations"] = answer_with_citations
    state["raw_sources"] = evidence_result["raw_sources"]
    state["evidence_nodes"] = evidence_result["evidence_nodes"]
    state["covered_concepts"] = evidence_result["covered_concepts"]
    state["missing_concepts"] = evidence_result["missing_concepts"]
    state["result_reason"] = (
        PARTIAL_COVERAGE_RESULT_REASON
        if evidence_result["coverage_status"] == "partial"
        else None
    )
    logger.info(
        "[AdaptiveRAG] generate_answer completed answer_len=%s citation_blocks=%s cited_chunk_ids=%s covered_concepts=%s missing_concepts=%s coverage_status=%s",
        len(answer),
        len(answer_with_citations),
        [citation.get("chunk_id") for citation in state.get("citations", [])],
        state.get("covered_concepts", []),
        state.get("missing_concepts", []),
        evidence_result["coverage_status"],
    )
    return state


async def grade_generation_node(state: AdaptiveRAGState, emit: EventCallback) -> AdaptiveRAGState:
    logger.info(
        "[AdaptiveRAG] grade_generation start answer_len=%s grounded_chunks=%s",
        len((state.get("answer") or "").strip()),
        len(state.get("filtered_documents", [])),
    )
    await _safe_emit(
        emit,
        "[grader] checking whether the generated answer is grounded and answers the question.",
        event_type="grader",
    )

    documents = state.get("filtered_documents", [])
    answer = (state.get("answer") or "").strip()
    answer_with_citations = state.get("answer_with_citations", [])
    required_concepts = state.get("query_intent", {}).get("required_concepts", [])
    covered_concepts = state.get("covered_concepts", [])
    missing_concepts = state.get("missing_concepts", [])

    if not answer or (not answer_with_citations and not state.get("citations")):
        state["result_reason"] = UNRELIABLE_RESULT_REASON
        logger.warning(
            "[AdaptiveRAG] grade_generation rejected due to missing answer_or_citations answer_len=%s citation_blocks=%s",
            len(answer),
            len(answer_with_citations),
        )
        return state

    document_preview = "\n\n".join(
        [
            f"[Document {idx}] {doc.get('source')} p.{doc.get('page')}\n{(doc.get('text') or '')[:MAX_DOC_PREVIEW_CHARS]}"
            for idx, doc in enumerate(documents, start=1)
        ]
    )
    schema = {
        "type": "object",
        "properties": {
            "grounded": {"type": "string", "enum": ["yes", "no"]},
            "coverage_status": {"type": "string", "enum": ["full", "partial", "insufficient"]},
            "reason": {"type": "string"},
        },
        "required": ["grounded", "coverage_status", "reason"],
    }
    prompt = f"""
You are verifying a RAG answer.
Return grounded=yes only if the answer is supported by the provided documents.
Return coverage_status=full only if the answer addresses all required concepts.
Return coverage_status=partial only if the answer correctly covers the supported concepts, explicitly names the missing concepts, and does not invent unsupported details.
Return coverage_status=insufficient if the answer misses supported content or overclaims beyond the documents.

Question:
{state["question"]}

Required concepts:
{required_concepts}

Covered concepts from retrieval:
{covered_concepts}

Missing concepts from retrieval:
{missing_concepts}

Answer:
{answer}

Documents:
{document_preview}
"""

    try:
        result = await generate_structured_json(
            prompt,
            schema,
            operation_name="Adaptive RAG grade generation",
            temperature=0.0,
        )
    except Exception as err:
        logger.warning("[AdaptiveRAG] generation grading failed; accepting answer: %s", err)
        return state

    coverage_status = result.get("coverage_status")
    if result.get("grounded") == "yes" and coverage_status in {"full", "partial"}:
        state["result_reason"] = (
            PARTIAL_COVERAGE_RESULT_REASON if missing_concepts or coverage_status == "partial" else None
        )
        logger.info(
            "[AdaptiveRAG] grade_generation accepted grounded=%s coverage_status=%s reason=%r",
            result.get("grounded"),
            coverage_status,
            (result.get("reason") or "")[:200],
        )
        return state

    state["result_reason"] = UNRELIABLE_RESULT_REASON
    logger.warning(
        "[AdaptiveRAG] grade_generation rejected grounded=%s coverage_status=%s reason=%r",
        result.get("grounded"),
        result.get("coverage_status"),
        (result.get("reason") or "")[:200],
    )
    return state


async def run_adaptive_rag_stream(question: str, selected_file_ids: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
    logger.info(
        "[AdaptiveRAG] stream_start question=%r selected_file_ids=%s",
        question[:160],
        selected_file_ids,
    )
    yield _make_event("Starting retrieval...", {"question": question}, event_type="retrieval")

    if not selected_file_ids:
        logger.warning("[AdaptiveRAG] stream_end empty_selection")
        yield _make_event("Please select at least one document for retrieval.", event_type="retrieval")
        return

    events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def emit(message: str, data: Any = None, event_type: str = "retrieval") -> None:
        await events.put(_make_event(message, data, event_type))

    state: AdaptiveRAGState = {
        "question": question.strip(),
        "original_question": question.strip(),
        "selected_file_ids": list(selected_file_ids),
        "current_query": question.strip(),
        "rewrite_count": 0,
        "generation_retry_count": 0,
        "candidate_documents": [],
        "filtered_documents": [],
        "query_intent": retrieval_intent.analyze_query_intent(question.strip()),
        "covered_concepts": [],
        "missing_concepts": [],
        "answer": "",
        "citations": [],
        "answer_with_citations": [],
        "raw_sources": [],
        "evidence_nodes": [],
        "result_reason": None,
    }

    async def flush_events() -> AsyncGenerator[Dict[str, Any], None]:
        while not events.empty():
            event = await events.get()
            yield event
            events.task_done()

    state = await route_question_node(state, emit)
    async for event in flush_events():
        yield event

    if state.get("route_decision") == "reject":
        state["result_reason"] = UNSUPPORTED_RESULT_REASON
        logger.info("[AdaptiveRAG] stream_end route_rejected result_reason=%s", state["result_reason"])
        yield _build_result_payload(
            state=state,
            question=question,
            answer=OUT_OF_SCOPE_ANSWER,
            answer_with_citations=[],
            raw_sources=[],
        )
        return

    while True:
        state = await retrieve_documents_node(state, emit)
        async for event in flush_events():
            yield event

        state = await grade_documents_node(state, emit)
        async for event in flush_events():
            yield event

        if state.get("filtered_documents"):
            state = await generate_answer_node(state, emit)
            async for event in flush_events():
                yield event

            state = await grade_generation_node(state, emit)
            async for event in flush_events():
                yield event

            if state.get("result_reason") != UNRELIABLE_RESULT_REASON:
                logger.info(
                    "[AdaptiveRAG] stream_end success answer_len=%s raw_sources=%s",
                    len(state.get("answer") or ""),
                    len(state.get("raw_sources", [])),
                )
                yield _make_event("[generation] answer generation completed.", event_type="generation")
                yield _build_result_payload(
                    state=state,
                    question=question,
                    answer=state.get("answer") or NO_DOCUMENTS_ANSWER,
                    answer_with_citations=state.get("answer_with_citations", []),
                    raw_sources=state.get("raw_sources", []),
                )
                return

            if state.get("generation_retry_count", 0) >= MAX_GENERATION_RETRIES:
                logger.warning(
                    "[AdaptiveRAG] stream_end generation_retry_limit reached retries=%s result_reason=%s",
                    state.get("generation_retry_count", 0),
                    state.get("result_reason"),
                )
                yield _build_result_payload(
                    state=state,
                    question=question,
                    answer=NO_DOCUMENTS_ANSWER,
                    answer_with_citations=[],
                    raw_sources=state.get("raw_sources", []),
                )
                return

            state["generation_retry_count"] = state.get("generation_retry_count", 0) + 1
            logger.info(
                "[AdaptiveRAG] generation_retry scheduled retry_count=%s",
                state["generation_retry_count"],
            )

        if state.get("rewrite_count", 0) >= MAX_REWRITE_ATTEMPTS:
            state["result_reason"] = state.get("result_reason") or NO_DOCUMENTS_RESULT_REASON
            logger.warning(
                "[AdaptiveRAG] stream_end rewrite_limit reached rewrite_count=%s result_reason=%s",
                state.get("rewrite_count", 0),
                state.get("result_reason"),
            )
            yield _build_result_payload(
                state=state,
                question=question,
                answer=NO_DOCUMENTS_ANSWER,
                answer_with_citations=[],
                raw_sources=state.get("raw_sources", []),
            )
            return

        state = await rewrite_query_node(state, emit)
        async for event in flush_events():
            yield event
