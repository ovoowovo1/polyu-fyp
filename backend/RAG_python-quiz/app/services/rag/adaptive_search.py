from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.logger import get_logger
from app.services.rag import retrieval_intent
from app.services.rag.adaptive_types import AdaptiveRetrievalState, EventCallback
from app.services.rag.rag_shared import normalize_doc, safe_emit
from app.services.rag.retrieval_fusion import merge_candidate_documents, reciprocal_rank_fusion
from app.services.rag.retrieval_hybrid import run_hybrid_search_for_query
from app.services.rag.retrieval_intent import QueryIntent, QuerySearchSpec, _clean_concept_fragment

logger = get_logger(__name__)

RRF_K = 60
RESERVED_CANDIDATES_PER_SUBQUERY = 2


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
) -> Dict[str, Any]:
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


def analyze_state_query_intent(state: AdaptiveRetrievalState) -> QueryIntent:
    previous_intent = state.get("query_intent", {})
    return retrieval_intent.analyze_query_intent(
        state["current_query"],
        fallback_required_concepts=previous_intent.get("required_concepts", []),
        fallback_intent_type=previous_intent.get("intent_type"),
    )


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
) -> List[Dict[str, Any]]:
    search_results = []
    for query_spec in query_intent["search_queries"]:
        search_results.append(
            await run_search_for_query(
                query_spec,
                selected_file_ids,
                emit,
                retrieval_k=retrieval_k,
                log_prefix=log_prefix,
                retrieve_vector_context_func=retrieve_vector_context_func,
                retrieve_context_by_keywords_func=retrieve_context_by_keywords_func,
                is_retryable_embedding_error_func=is_retryable_embedding_error_func,
            )
        )
    return search_results


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
) -> AdaptiveRetrievalState:
    current_query = state["current_query"]
    selected_file_ids = state["selected_file_ids"]
    query_intent = analyze_state_query_intent(state)
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
