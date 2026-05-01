from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypedDict

from app.logger import get_logger
from app.services import pg_service
from app.services.ai_service import generate_structured_json
from app.services.rag_shared import normalize_concepts, normalize_doc, safe_emit
from app.services.retrieval_fusion import merge_candidate_documents, reciprocal_rank_fusion
from app.services import retrieval_intent
from app.services.retrieval_hybrid import run_hybrid_search_for_query
from app.services.retrieval_intent import (
    QueryIntent,
    QuerySearchSpec,
    _clean_concept_fragment,
)
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
RESERVED_CANDIDATES_PER_SUBQUERY = 2


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
    query_intent: QueryIntent
    covered_concepts: List[str]
    missing_concepts: List[str]


class AdaptiveRetrievalResult(TypedDict, total=False):
    documents: List[Dict[str, Any]]
    candidate_documents: List[Dict[str, Any]]
    rewrite_count: int
    current_query: str
    fallback_reason: str | None
    retrieval_mode_summary: Dict[str, Any]
    vector_retrieval_degraded: bool
    query_intent: QueryIntent
    covered_concepts: List[str]
    missing_concepts: List[str]


EventCallback = Callable[[str, Any, str], Awaitable[None]]


async def _safe_emit(callback: EventCallback, message: str, data: Any = None, event_type: str = "retrieval") -> None:
    await safe_emit(callback, message, data, event_type)


def _normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_doc(
        doc,
        normalize_concept_fields=("retrieved_for_concepts", "covered_concepts"),
        concept_normalizer=_clean_concept_fragment,
    )


def _reciprocal_rank_fusion(results_list: List[List[Dict[str, Any]]], k: int = RRF_K) -> List[Dict[str, Any]]:
    return reciprocal_rank_fusion(results_list, normalize_doc=_normalize_doc, k=k)


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


async def _run_hybrid_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
) -> Dict[str, Any]:
    return await run_hybrid_search_for_query(
        query_spec,
        selected_file_ids,
        emit,
        retrieval_k=retrieval_k,
        log_prefix=log_prefix,
        logger=logger,
        safe_emit=_safe_emit,
        normalize_doc=_normalize_doc,
        retrieve_vector_context=_retrieve_vector_context,
        retrieve_context_by_keywords=pg_service.retrieve_context_by_keywords,
        reciprocal_rank_fusion_func=_reciprocal_rank_fusion,
        is_retryable_embedding_error=is_retryable_embedding_error,
        rrf_k=RRF_K,
    )


def _merge_candidate_documents(
    search_results: Sequence[Dict[str, Any]],
    *,
    max_docs_to_grade: int,
) -> List[Dict[str, Any]]:
    return merge_candidate_documents(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
        normalize_doc=_normalize_doc,
        reciprocal_rank_fusion_func=_reciprocal_rank_fusion,
        rrf_k=RRF_K,
        reserved_candidates_per_subquery=RESERVED_CANDIDATES_PER_SUBQUERY,
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
    previous_intent = state.get("query_intent", {})
    query_intent = retrieval_intent.analyze_query_intent(
        current_query,
        fallback_required_concepts=previous_intent.get("required_concepts", []),
        fallback_intent_type=previous_intent.get("intent_type"),
    )
    state["query_intent"] = query_intent
    logger.info(
        "[%s] retrieve_documents start query=%r rewrite_count=%s selected_files=%s mode=%s intent_type=%s required_concepts=%s",
        log_prefix,
        current_query[:160],
        state.get("rewrite_count", 0),
        len(selected_file_ids),
        query_intent["mode"],
        query_intent["intent_type"],
        query_intent["required_concepts"],
    )

    search_results = []
    for query_spec in query_intent["search_queries"]:
        search_results.append(
            await _run_hybrid_search_for_query(
                query_spec,
                selected_file_ids,
                emit,
                retrieval_k=retrieval_k,
                log_prefix=log_prefix,
            )
        )

    candidate_documents = _merge_candidate_documents(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
    )

    vector_hits = sum(len(result["vector_results"]) for result in search_results)
    fulltext_hits = sum(len(result["fulltext_results"]) for result in search_results)
    vector_failed = any(result["vector_failed"] for result in search_results)
    fulltext_failed = any(result["fulltext_failed"] for result in search_results)
    vector_retrieval_degraded = any(result["vector_retrieval_degraded"] for result in search_results)
    state["candidate_documents"] = candidate_documents
    state["covered_concepts"] = []
    state["missing_concepts"] = list(query_intent["required_concepts"])
    state["vector_retrieval_degraded"] = vector_retrieval_degraded
    state["retrieval_mode_summary"] = {
        "vector_hits": vector_hits,
        "fulltext_hits": fulltext_hits,
        "vector_failed": vector_failed,
        "fulltext_failed": fulltext_failed,
        "vector_retrieval_degraded": vector_retrieval_degraded,
        "subquery_summaries": [
            {
                "label": result["query_spec"]["label"],
                "query": result["query_spec"]["query"],
                "concept": result["query_spec"].get("concept"),
                "query_kind": result["query_spec"].get("query_kind"),
                "vector_hits": len(result["vector_results"]),
                "fulltext_hits": len(result["fulltext_results"]),
                "retrieval_mode": result["retrieval_mode"],
                "top_chunk_ids": [doc.get("chunkId") for doc in result["fused"][:5]],
            }
            for result in search_results
        ],
    }
    logger.info(
        "[%s] retrieval merged_candidates=%s top_sources=%s",
        log_prefix,
        len(candidate_documents),
        [
            {
                "chunk_id": doc.get("chunkId"),
                "source": doc.get("source"),
                "score": doc.get("rrf_score"),
                "retrieved_for_concepts": doc.get("retrieved_for_concepts", []),
            }
            for doc in candidate_documents[:5]
        ],
    )

    await _safe_emit(
        emit,
        f"[retrieval] merged results produced {len(candidate_documents)} candidate chunks.",
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
    query_intent = state.get("query_intent") or retrieval_intent.analyze_query_intent(question)
    required_concepts = query_intent.get("required_concepts", [])
    intent_type = query_intent.get("intent_type", "single")
    filtered_documents: List[Dict[str, Any]] = []
    logger.info(
        "[%s] grade_documents start question=%r candidate_chunks=%s required_concepts=%s intent_type=%s",
        log_prefix,
        question[:160],
        len(candidate_documents),
        required_concepts,
        intent_type,
    )

    await _safe_emit(
        emit,
        f"[grader] grading {len(candidate_documents)} retrieved chunks for relevance.",
        len(candidate_documents),
        "grader",
    )

    if required_concepts:
        schema = {
            "type": "object",
            "properties": {
                "relevant": {"type": "string", "enum": ["yes", "no"]},
                "covered_concepts": {
                    "type": "array",
                    "items": {"type": "string", "enum": required_concepts},
                },
                "reason": {"type": "string"},
            },
            "required": ["relevant", "covered_concepts", "reason"],
        }
    else:
        schema = {
            "type": "object",
            "properties": {
                "relevant": {"type": "string", "enum": ["yes", "no"]},
                "reason": {"type": "string"},
            },
            "required": ["relevant", "reason"],
        }

    semaphore = asyncio.Semaphore(DOCUMENT_GRADING_CONCURRENCY) if DOCUMENT_GRADING_CONCURRENCY else None

    async def grade_one(index: int, doc: Dict[str, Any]) -> tuple[int, bool, Dict[str, Any], List[str]]:
        retrieved_for = normalize_concepts(doc.get("retrieved_for_concepts", []), normalizer=_clean_concept_fragment)
        if required_concepts:
            concept_lines = "\n".join(f"- {concept}" for concept in required_concepts)
            prompt = f"""
You are filtering retrieval chunks for a multi-concept RAG system.
Intent type: {intent_type}
- Mark relevant=yes only if this chunk directly supports at least one required concept or directly helps compare the required concepts.
- Do not treat incidental mentions as evidence.
- Return only the concepts that are directly supported by this chunk itself.

User question:
{question}

Required concepts:
{concept_lines}

Chunk surfaced for concepts (retrieval hint only, not evidence):
{retrieved_for}

Document:
Source: {doc.get("source")}
Page: {doc.get("page")}
Content:
{(doc.get("text") or "")[:MAX_DOC_PREVIEW_CHARS]}
"""
        else:
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

            covered = normalize_concepts(result.get("covered_concepts", []), normalizer=_clean_concept_fragment)
            should_keep = result.get("relevant") == "yes"
            logger.info(
                "[%s] grade_document chunk_id=%s relevant=%s retrieved_for=%s covered=%s source=%r reason=%r",
                log_prefix,
                doc.get("chunkId"),
                result.get("relevant"),
                retrieved_for,
                covered,
                doc.get("source"),
                (result.get("reason") or "")[:200],
            )
            merged_doc = {**doc, "covered_concepts": covered}
            return index, should_keep, merged_doc, covered
        except Exception as err:
            logger.warning("[%s] document grading failed; keeping chunk %s: %s", log_prefix, doc.get("chunkId"), err)
            merged_doc = {**doc, "covered_concepts": []}
            return index, True, merged_doc, []

    grading_results = await asyncio.gather(
        *(grade_one(index, doc) for index, doc in enumerate(candidate_documents))
    )
    grading_results.sort(key=lambda item: item[0])

    covered_concepts: List[str] = []
    for _, should_keep, doc, doc_covered_concepts in grading_results:
        if should_keep:
            filtered_documents.append(doc)
            covered_concepts = normalize_concepts(
                covered_concepts + doc_covered_concepts,
                normalizer=_clean_concept_fragment,
            )

    missing_concepts = [concept for concept in required_concepts if concept not in covered_concepts]
    state["filtered_documents"] = filtered_documents
    state["covered_concepts"] = covered_concepts
    state["missing_concepts"] = missing_concepts
    logger.info(
        "[%s] grade_documents kept_chunks=%s kept_chunk_ids=%s covered_concepts=%s missing_concepts=%s",
        log_prefix,
        len(filtered_documents),
        [doc.get("chunkId") for doc in filtered_documents],
        covered_concepts,
        missing_concepts,
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
    query_intent = state.get("query_intent") or retrieval_intent.analyze_query_intent(state.get("original_question", ""))
    logger.info(
        "[%s] rewrite_query start attempt=%s original_question=%r current_query=%r intent_type=%s required_concepts=%s",
        log_prefix,
        rewrite_count,
        state.get("original_question", "")[:160],
        state.get("current_query", "")[:160],
        query_intent.get("intent_type"),
        query_intent.get("required_concepts", []),
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
- Keep the original intent and all required concepts.
- Preserve the question style: if it is a comparison, keep it as a comparison; if it is asking for definitions, keep it as a definition query.
- Prefer domain keywords, entity names, and technical terms.
- Do not answer the question.
- Return one short query.

Original question:
{state["original_question"]}

Detected intent type:
{query_intent.get("intent_type", "single")}

Required concepts:
{query_intent.get("required_concepts", [])}
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
    state["query_intent"] = retrieval_intent.analyze_query_intent(
        state["current_query"],
        fallback_required_concepts=query_intent.get("required_concepts", []),
        fallback_intent_type=query_intent.get("intent_type"),
    )
    logger.info(
        "[%s] rewrite_query completed attempt=%s rewritten_query=%r preserved_intent_type=%s preserved_required_concepts=%s",
        log_prefix,
        rewrite_count,
        state["current_query"][:160],
        state["query_intent"].get("intent_type"),
        state["query_intent"].get("required_concepts", []),
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

    initial_intent = retrieval_intent.analyze_query_intent(question.strip())

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
                "subquery_summaries": [],
            },
            "vector_retrieval_degraded": False,
            "query_intent": initial_intent,
            "covered_concepts": [],
            "missing_concepts": initial_intent["required_concepts"],
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
        "query_intent": initial_intent,
        "covered_concepts": [],
        "missing_concepts": [],
        "retrieval_mode_summary": {
            "vector_hits": 0,
            "fulltext_hits": 0,
            "vector_failed": False,
            "fulltext_failed": False,
            "vector_retrieval_degraded": False,
            "subquery_summaries": [],
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
                "[%s] run_end success kept_chunks=%s rewrite_count=%s covered_concepts=%s missing_concepts=%s",
                log_prefix,
                len(state.get("filtered_documents", [])),
                state.get("rewrite_count", 0),
                state.get("covered_concepts", []),
                state.get("missing_concepts", []),
            )
            return {
                "documents": state.get("filtered_documents", []),
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": None,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
                "query_intent": state.get("query_intent", initial_intent),
                "covered_concepts": state.get("covered_concepts", []),
                "missing_concepts": state.get("missing_concepts", []),
            }

        if state.get("rewrite_count", 0) >= max_rewrite_attempts:
            logger.warning(
                "[%s] run_end no_documents rewrite_count=%s fallback_reason=%s missing_concepts=%s",
                log_prefix,
                state.get("rewrite_count", 0),
                NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
                state.get("missing_concepts", []),
            )
            return {
                "documents": [],
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
                "query_intent": state.get("query_intent", initial_intent),
                "covered_concepts": state.get("covered_concepts", []),
                "missing_concepts": state.get("missing_concepts", []),
            }

        state = await rewrite_query_node(
            state,
            emit_callback,
            max_rewrite_attempts=max_rewrite_attempts,
            log_prefix=log_prefix,
        )
