from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Sequence, TypedDict

from app.logger import get_logger
from app.services import pg_service
from app.services.ai_service import generate_structured_json
from app.services.vector_query_service import is_retryable_embedding_error, retrieve_vector_context

logger = get_logger(__name__)

MAX_DOCS_TO_GRADE = 8
MAX_REWRITE_ATTEMPTS = 1
RETRIEVAL_K = 20
RRF_K = 60
MAX_DOC_PREVIEW_CHARS = 1800
DOCUMENT_GRADING_CONCURRENCY: int | None = None
NO_RELEVANT_DOCUMENTS_FALLBACK_REASON = "no_relevant_documents"
EMPTY_SELECTION_FALLBACK_REASON = "empty_selection"


class AdaptiveRetrievalState(TypedDict, total=False):
    question: str
    original_question: str
    selected_file_ids: List[str]
    current_query: str
    rewrite_count: int
    candidate_documents: List[Dict[str, Any]]
    filtered_documents: List[Dict[str, Any]]
    retrieval_mode_summary: Dict[str, Any]
    vector_retrieval_degraded: bool
    fallback_reason: str | None


class AdaptiveRetrievalResult(TypedDict, total=False):
    documents: List[Dict[str, Any]]
    candidate_documents: List[Dict[str, Any]]
    rewrite_count: int
    current_query: str
    fallback_reason: str | None
    retrieval_mode_summary: Dict[str, Any]
    vector_retrieval_degraded: bool


EventCallback = Callable[[str, Any, str], Awaitable[None]]


async def _safe_emit(callback: EventCallback, message: str, data: Any = None, event_type: str = "retrieval") -> None:
    await callback(message, data, event_type)


def _normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    page = (
        doc.get("page")
        or doc.get("pageNumber")
        or doc.get("page_start")
        or doc.get("pageStart")
        or "Unknown page"
    )
    source = doc.get("source") or doc.get("document_name") or "Unknown source"
    text = doc.get("content") or doc.get("text") or ""
    file_id = doc.get("fileId") or doc.get("fileid")
    chunk_id = doc.get("chunkId") or doc.get("chunkid")
    return {
        **doc,
        "text": text,
        "content": text,
        "source": source,
        "page": page,
        "fileId": file_id,
        "chunkId": chunk_id,
    }


def _reciprocal_rank_fusion(results_list: List[List[Dict[str, Any]]], k: int = RRF_K) -> List[Dict[str, Any]]:
    rrf_scores: Dict[str, Dict[str, Any]] = {}

    for results in results_list:
        for rank, raw_doc in enumerate(results, start=1):
            doc = _normalize_doc(raw_doc)
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            score = 1.0 / (k + rank)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {
                    "doc": doc,
                    "rrf_score": 0.0,
                }
            rrf_scores[chunk_id]["rrf_score"] += score

    sorted_docs = sorted(rrf_scores.values(), key=lambda item: item["rrf_score"], reverse=True)
    return [{**item["doc"], "rrf_score": round(item["rrf_score"], 4)} for item in sorted_docs]


async def _retrieve_vector_context(
    question: str,
    selected_file_ids: Sequence[str],
    *,
    k: int = RETRIEVAL_K,
    log_prefix: str = "vector retrieval",
) -> tuple[List[Dict[str, Any]], str]:
    return await retrieve_vector_context(
        question,
        selected_file_ids,
        k=k,
        log_prefix=log_prefix,
    )


async def retrieve_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    retrieval_k: int = RETRIEVAL_K,
    max_docs_to_grade: int = MAX_DOCS_TO_GRADE,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    current_query = state["current_query"]
    selected_file_ids = state["selected_file_ids"]
    logger.info(
        "[%s] retrieve_documents start query=%r rewrite_count=%s selected_files=%s",
        log_prefix,
        current_query[:160],
        state.get("rewrite_count", 0),
        len(selected_file_ids),
    )

    await _safe_emit(
        emit,
        f"[retrieval] retrieving candidate chunks for query: {current_query}",
        event_type="retrieval",
    )

    vector_failed = False
    vector_retrieval_degraded = False
    fulltext_failed = False

    async def run_vector_search() -> List[Dict[str, Any]]:
        nonlocal vector_failed, vector_retrieval_degraded

        try:
            rows, retrieval_mode = await _retrieve_vector_context(
                current_query,
                selected_file_ids,
                k=retrieval_k,
                log_prefix=log_prefix,
            )
            await _safe_emit(
                emit,
                f"[retrieval] vector search completed with {len(rows)} hits ({retrieval_mode}).",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] vector_search hits=%s mode=%s top_chunk_ids=%s",
                log_prefix,
                len(rows),
                retrieval_mode,
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [_normalize_doc(row) for row in rows]
        except Exception as err:
            vector_failed = True
            vector_retrieval_degraded = is_retryable_embedding_error(err)
            logger.warning("[%s] vector retrieval failed: %s", log_prefix, err)
            await _safe_emit(
                emit,
                f"[retrieval] vector search failed: {err}",
                0,
                "retrieval",
            )
            return []

    async def run_fulltext_search() -> List[Dict[str, Any]]:
        nonlocal fulltext_failed

        try:
            rows = await asyncio.to_thread(
                pg_service.retrieve_context_by_keywords,
                current_query,
                selected_file_ids,
                retrieval_k,
            )
            await _safe_emit(
                emit,
                f"[retrieval] fulltext search completed with {len(rows)} hits.",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] fulltext_search hits=%s top_chunk_ids=%s",
                log_prefix,
                len(rows),
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [_normalize_doc(row) for row in rows]
        except Exception as err:
            fulltext_failed = True
            logger.warning("[%s] fulltext retrieval failed: %s", log_prefix, err)
            await _safe_emit(
                emit,
                f"[retrieval] fulltext search failed: {err}",
                0,
                "retrieval",
            )
            return []

    vector_results, fulltext_results = await asyncio.gather(
        run_vector_search(),
        run_fulltext_search(),
    )
    logger.info(
        "[%s] retrieval gathered vector_hits=%s fulltext_hits=%s",
        log_prefix,
        len(vector_results),
        len(fulltext_results),
    )
    fused = _reciprocal_rank_fusion([vector_results, fulltext_results], k=RRF_K)
    candidate_documents = fused[:max_docs_to_grade]
    state["candidate_documents"] = candidate_documents
    state["vector_retrieval_degraded"] = vector_retrieval_degraded
    state["retrieval_mode_summary"] = {
        "vector_hits": len(vector_results),
        "fulltext_hits": len(fulltext_results),
        "vector_failed": vector_failed,
        "fulltext_failed": fulltext_failed,
        "vector_retrieval_degraded": vector_retrieval_degraded,
    }
    logger.info(
        "[%s] retrieval fused_candidates=%s top_sources=%s",
        log_prefix,
        len(candidate_documents),
        [
            {
                "chunk_id": doc.get("chunkId"),
                "source": doc.get("source"),
                "score": doc.get("rrf_score"),
            }
            for doc in candidate_documents[:5]
        ],
    )

    await _safe_emit(
        emit,
        f"[retrieval] fused results produced {len(candidate_documents)} candidate chunks.",
        len(candidate_documents),
        "retrieval",
    )
    return state


async def grade_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    question = state["question"]
    candidate_documents = state.get("candidate_documents", [])
    filtered_documents: List[Dict[str, Any]] = []
    logger.info(
        "[%s] grade_documents start question=%r candidate_chunks=%s",
        log_prefix,
        question[:160],
        len(candidate_documents),
    )

    await _safe_emit(
        emit,
        f"[grader] grading {len(candidate_documents)} retrieved chunks for relevance.",
        len(candidate_documents),
        "grader",
    )

    schema = {
        "type": "object",
        "properties": {
            "relevant": {"type": "string", "enum": ["yes", "no"]},
            "reason": {"type": "string"},
        },
        "required": ["relevant", "reason"],
    }

    semaphore = asyncio.Semaphore(DOCUMENT_GRADING_CONCURRENCY) if DOCUMENT_GRADING_CONCURRENCY else None

    async def grade_one(index: int, doc: Dict[str, Any]) -> tuple[int, bool, Dict[str, Any]]:
        prompt = f"""
You are filtering retrieval chunks for a RAG system.
Mark a document as relevant only if it contains information that helps answer the question directly.

Question:
{question}

Document:
Source: {doc.get("source")}
Page: {doc.get("page")}
Content:
{(doc.get("text") or "")[:MAX_DOC_PREVIEW_CHARS]}
"""
        try:
            if semaphore is None:
                result = await generate_structured_json(
                    prompt,
                    schema,
                    operation_name="Adaptive RAG grade document",
                    temperature=0.0,
                )
            else:
                async with semaphore:
                    result = await generate_structured_json(
                        prompt,
                        schema,
                        operation_name="Adaptive RAG grade document",
                        temperature=0.0,
                    )
            logger.info(
                "[%s] grade_document chunk_id=%s relevant=%s source=%r reason=%r",
                log_prefix,
                doc.get("chunkId"),
                result.get("relevant"),
                doc.get("source"),
                (result.get("reason") or "")[:200],
            )
            return index, result.get("relevant") == "yes", doc
        except Exception as err:
            logger.warning("[%s] document grading failed; keeping chunk %s: %s", log_prefix, doc.get("chunkId"), err)
            return index, True, doc

    grading_results = await asyncio.gather(
        *(grade_one(index, doc) for index, doc in enumerate(candidate_documents))
    )
    grading_results.sort(key=lambda item: item[0])

    for _, should_keep, doc in grading_results:
        if should_keep:
            filtered_documents.append(doc)

    state["filtered_documents"] = filtered_documents
    logger.info(
        "[%s] grade_documents kept_chunks=%s kept_chunk_ids=%s",
        log_prefix,
        len(filtered_documents),
        [doc.get("chunkId") for doc in filtered_documents],
    )
    await _safe_emit(
        emit,
        f"[grader] kept {len(filtered_documents)} relevant chunks.",
        len(filtered_documents),
        "grader",
    )
    return state


async def rewrite_query_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    max_rewrite_attempts: int = MAX_REWRITE_ATTEMPTS,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    rewrite_count = state.get("rewrite_count", 0) + 1
    state["rewrite_count"] = rewrite_count
    logger.info(
        "[%s] rewrite_query start attempt=%s original_question=%r current_query=%r",
        log_prefix,
        rewrite_count,
        state.get("original_question", "")[:160],
        state.get("current_query", "")[:160],
    )

    await _safe_emit(
        emit,
        f"[rewrite] rewriting query (attempt {rewrite_count}/{max_rewrite_attempts}).",
        rewrite_count,
        "rewrite",
    )

    schema = {
        "type": "object",
        "properties": {
            "rewritten_query": {"type": "string"},
        },
        "required": ["rewritten_query"],
    }
    prompt = f"""
Rewrite the user question into a concise retrieval query for searching within course documents.
- Keep the original intent.
- Prefer domain keywords, entity names, and technical terms.
- Do not answer the question.
- Return one short query.

Question:
{state["original_question"]}
"""

    try:
        result = await generate_structured_json(
            prompt,
            schema,
            operation_name="Adaptive RAG rewrite query",
            temperature=0.0,
        )
        rewritten_query = (result.get("rewritten_query") or "").strip()
    except Exception as err:
        logger.warning("[%s] query rewrite failed; using original question: %s", log_prefix, err)
        rewritten_query = ""

    state["current_query"] = rewritten_query or state["original_question"]
    logger.info(
        "[%s] rewrite_query completed attempt=%s rewritten_query=%r",
        log_prefix,
        rewrite_count,
        state["current_query"][:160],
    )
    await _safe_emit(
        emit,
        f"[rewrite] rewritten query: {state['current_query']}",
        state["current_query"],
        "rewrite",
    )
    return state


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
    async def noop_emit(message: str, data: Any = None, event_type: str = "retrieval") -> None:
        return None

    emit_callback = emit or noop_emit
    logger.info(
        "[%s] run_start question=%r selected_files=%s retrieval_k=%s max_docs_to_grade=%s",
        log_prefix,
        question[:160],
        len(selected_file_ids),
        retrieval_k,
        max_docs_to_grade,
    )

    if not selected_file_ids:
        logger.warning("[%s] run_end empty_selection", log_prefix)
        return {
            "documents": [],
            "candidate_documents": [],
            "rewrite_count": 0,
            "current_query": question.strip(),
            "fallback_reason": EMPTY_SELECTION_FALLBACK_REASON,
            "retrieval_mode_summary": {
                "vector_hits": 0,
                "fulltext_hits": 0,
                "vector_failed": False,
                "fulltext_failed": False,
                "vector_retrieval_degraded": False,
            },
            "vector_retrieval_degraded": False,
        }

    state: AdaptiveRetrievalState = {
        "question": question.strip(),
        "original_question": question.strip(),
        "selected_file_ids": list(selected_file_ids),
        "current_query": question.strip(),
        "rewrite_count": 0,
        "candidate_documents": [],
        "filtered_documents": [],
        "fallback_reason": None,
        "retrieval_mode_summary": {
            "vector_hits": 0,
            "fulltext_hits": 0,
            "vector_failed": False,
            "fulltext_failed": False,
            "vector_retrieval_degraded": False,
        },
        "vector_retrieval_degraded": False,
    }

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
                "[%s] run_end success kept_chunks=%s rewrite_count=%s",
                log_prefix,
                len(state.get("filtered_documents", [])),
                state.get("rewrite_count", 0),
            )
            return {
                "documents": state.get("filtered_documents", []),
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": None,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
            }

        if state.get("rewrite_count", 0) >= max_rewrite_attempts:
            logger.warning(
                "[%s] run_end no_documents rewrite_count=%s fallback_reason=%s",
                log_prefix,
                state.get("rewrite_count", 0),
                NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
            )
            return {
                "documents": [],
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
            }

        state = await rewrite_query_node(
            state,
            emit_callback,
            max_rewrite_attempts=max_rewrite_attempts,
            log_prefix=log_prefix,
        )
