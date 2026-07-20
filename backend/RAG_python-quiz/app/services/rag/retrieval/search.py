from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Sequence

from app.logger import get_logger
from app.services.rag.retrieval import intent as retrieval_intent
from app.services.rag.retrieval.types import AdaptiveRetrievalState, EventCallback
from app.services.rag.shared.helpers import normalize_doc, safe_emit
from app.services.rag.retrieval.fusion import merge_candidate_documents, reciprocal_rank_fusion
from app.services.rag.retrieval.hybrid import run_hybrid_search_for_query
from app.services.rag.retrieval.intent import QueryIntent, QuerySearchSpec, _clean_concept_fragment

logger = get_logger(__name__)

RRF_K = 60
RESERVED_CANDIDATES_PER_SUBQUERY = 2
SUBQUERY_RETRIEVAL_CONCURRENCY = 8


def normalize_retrieval_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_doc(
        doc,
        normalize_concept_fields=("retrieved_for_concepts", "covered_concepts"),
        concept_normalizer=_clean_concept_fragment,
    )


def fuse_ranked_results(results_list: List[List[Dict[str, Any]]], k: int = RRF_K) -> List[Dict[str, Any]]:
    return reciprocal_rank_fusion(results_list, normalize_doc=normalize_retrieval_doc, k=k)


async def run_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
    retrieve_vector_context_func,
    retrieve_context_by_keywords_func,
    is_retryable_embedding_error_func,
    semaphore: asyncio.Semaphore | None = None,
) -> Dict[str, Any]:
    async def run() -> Dict[str, Any]:
        return await run_hybrid_search_for_query(
            query_spec,
            selected_file_ids,
            emit,
            retrieval_k=retrieval_k,
            log_prefix=log_prefix,
            logger=logger,
            safe_emit=safe_emit,
            normalize_doc=normalize_retrieval_doc,
            retrieve_vector_context=retrieve_vector_context_func,
            retrieve_context_by_keywords=retrieve_context_by_keywords_func,
            reciprocal_rank_fusion_func=fuse_ranked_results,
            is_retryable_embedding_error=is_retryable_embedding_error_func,
            rrf_k=RRF_K,
        )

    if semaphore is None:
        return await run()
    async with semaphore:
        return await run()


def merge_retrieval_candidates(
    search_results: Sequence[Dict[str, Any]],
    *,
    max_docs_to_grade: int,
) -> List[Dict[str, Any]]:
    return merge_candidate_documents(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
        normalize_doc=normalize_retrieval_doc,
        reciprocal_rank_fusion_func=fuse_ranked_results,
        rrf_k=RRF_K,
        reserved_candidates_per_subquery=RESERVED_CANDIDATES_PER_SUBQUERY,
    )


async def analyze_state_query_intent(
    state: AdaptiveRetrievalState,
    *,
    classify_query_intent_func,
) -> QueryIntent:
    current_query = state["current_query"]
    previous_intent = state.get("query_intent")
    if previous_intent and state.get("classified_query") in {None, current_query}:
        return previous_intent
    return await classify_query_intent_func(current_query)


async def collect_search_results(
    query_intent: QueryIntent,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
    retrieve_vector_context_func,
    retrieve_context_by_keywords_func,
    is_retryable_embedding_error_func,
    concurrency: int = SUBQUERY_RETRIEVAL_CONCURRENCY,
) -> List[Dict[str, Any]]:
    query_specs = list(query_intent["search_queries"])
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def collect_one(query_spec: QuerySearchSpec) -> Dict[str, Any]:
        try:
            return await run_search_for_query(
                query_spec,
                selected_file_ids,
                emit,
                retrieval_k=retrieval_k,
                log_prefix=log_prefix,
                retrieve_vector_context_func=retrieve_vector_context_func,
                retrieve_context_by_keywords_func=retrieve_context_by_keywords_func,
                is_retryable_embedding_error_func=is_retryable_embedding_error_func,
                semaphore=semaphore,
            )
        except Exception as err:
            logger.warning(
                "[%s] subquery retrieval failed label=%r query=%r: %s",
                log_prefix,
                query_spec["label"],
                query_spec["query"][:160],
                err,
            )
            await safe_emit(
                emit,
                f"[retrieval] subquery failed for {query_spec['label']}: {err}",
                0,
                "retrieval",
            )
            return {
                "query_spec": query_spec,
                "vector_results": [],
                "fulltext_results": [],
                "fused": [],
                "vector_failed": True,
                "fulltext_failed": True,
                "vector_retrieval_degraded": False,
                "retrieval_mode": "failed",
            }

    return list(await asyncio.gather(*(collect_one(query_spec) for query_spec in query_specs)))


def build_targeted_retry_query_specs(
    query_intent: QueryIntent,
    current_query: str,
    missing_concepts: Sequence[str],
) -> List[QuerySearchSpec]:
    required_by_key = {concept.casefold(): concept for concept in query_intent["required_concepts"]}
    specs: List[QuerySearchSpec] = []
    for missing_concept in missing_concepts:
        canonical = required_by_key.get(missing_concept.casefold())
        if not canonical:
            continue
        specs.append(
            {
                "label": f"targeted support: {canonical}",
                "query": " ".join([canonical, current_query]).strip(),
                "concept": canonical,
                "query_kind": "targeted_concept_retry",
            }
        )
    return specs


def merge_retrieval_mode_summaries(
    previous: Dict[str, Any],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "vector_hits": previous.get("vector_hits", 0) + current.get("vector_hits", 0),
        "fulltext_hits": previous.get("fulltext_hits", 0) + current.get("fulltext_hits", 0),
        "vector_failed": previous.get("vector_failed", False) or current.get("vector_failed", False),
        "fulltext_failed": previous.get("fulltext_failed", False) or current.get("fulltext_failed", False),
        "vector_retrieval_degraded": previous.get("vector_retrieval_degraded", False)
        or current.get("vector_retrieval_degraded", False),
        "subquery_summaries": previous.get("subquery_summaries", []) + current.get("subquery_summaries", []),
    }


def build_retrieval_mode_summary(search_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "vector_hits": sum(len(result["vector_results"]) for result in search_results),
        "fulltext_hits": sum(len(result["fulltext_results"]) for result in search_results),
        "vector_failed": any(result["vector_failed"] for result in search_results),
        "fulltext_failed": any(result["fulltext_failed"] for result in search_results),
        "vector_retrieval_degraded": any(result["vector_retrieval_degraded"] for result in search_results),
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


async def retrieve_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    retrieval_k: int,
    max_docs_to_grade: int,
    log_prefix: str,
    retrieve_vector_context_func,
    retrieve_context_by_keywords_func,
    is_retryable_embedding_error_func,
    classify_query_intent_func,
) -> AdaptiveRetrievalState:
    current_query = state["current_query"]
    selected_file_ids = state["selected_file_ids"]
    query_intent = await analyze_state_query_intent(
        state,
        classify_query_intent_func=classify_query_intent_func,
    )
    state["query_intent"] = query_intent
    state["classified_query"] = current_query
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

    search_results = await collect_search_results(
        query_intent,
        selected_file_ids,
        emit,
        retrieval_k=retrieval_k,
        log_prefix=log_prefix,
        retrieve_vector_context_func=retrieve_vector_context_func,
        retrieve_context_by_keywords_func=retrieve_context_by_keywords_func,
        is_retryable_embedding_error_func=is_retryable_embedding_error_func,
    )
    candidate_documents = merge_retrieval_candidates(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
    )
    retrieval_mode_summary = build_retrieval_mode_summary(search_results)

    state["candidate_documents"] = candidate_documents
    state["covered_concepts"] = []
    state["missing_concepts"] = list(query_intent["required_concepts"])
    state["vector_retrieval_degraded"] = retrieval_mode_summary["vector_retrieval_degraded"]
    state["retrieval_mode_summary"] = retrieval_mode_summary
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

    await safe_emit(
        emit,
        f"[retrieval] merged results produced {len(candidate_documents)} candidate chunks.",
        len(candidate_documents),
        "retrieval",
    )
    return state


async def retry_missing_concepts_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    retrieval_k: int,
    max_docs_to_grade: int,
    log_prefix: str,
    retrieve_vector_context_func,
    retrieve_context_by_keywords_func,
    is_retryable_embedding_error_func,
) -> AdaptiveRetrievalState:
    query_intent = state.get("query_intent")
    if not query_intent:
        state["candidate_documents"] = []
        return state

    query_specs = build_targeted_retry_query_specs(
        query_intent,
        state.get("current_query", state.get("question", "")),
        state.get("missing_concepts", []),
    )
    if not query_specs:
        state["candidate_documents"] = []
        return state

    retry_intent = {**query_intent, "search_queries": query_specs}
    search_results = await collect_search_results(
        retry_intent,
        state["selected_file_ids"],
        emit,
        retrieval_k=retrieval_k,
        log_prefix=f"{log_prefix}:targeted_retry",
        retrieve_vector_context_func=retrieve_vector_context_func,
        retrieve_context_by_keywords_func=retrieve_context_by_keywords_func,
        is_retryable_embedding_error_func=is_retryable_embedding_error_func,
    )
    candidates = merge_retrieval_candidates(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
    )
    existing_ids = {doc.get("chunkId") for doc in state.get("filtered_documents", [])}
    state["candidate_documents"] = [doc for doc in candidates if doc.get("chunkId") not in existing_ids]
    retry_summary = build_retrieval_mode_summary(search_results)
    state["retrieval_mode_summary"] = merge_retrieval_mode_summaries(
        state.get("retrieval_mode_summary", {}),
        retry_summary,
    )
    state["vector_retrieval_degraded"] = state.get("vector_retrieval_degraded", False) or retry_summary[
        "vector_retrieval_degraded"
    ]
    await safe_emit(
        emit,
        f"[retrieval] targeted retry produced {len(state['candidate_documents'])} candidate chunks.",
        len(state["candidate_documents"]),
        "retrieval",
    )
    return state
