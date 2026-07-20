from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from app.services.rag.retrieval import hybrid_search as retrieval_hybrid_search
from app.services.rag.retrieval.intent import QuerySearchSpec

EventCallback = Callable[[str, Any, str], Awaitable[None]]
EmitFunc = Callable[[EventCallback, str, Any, str], Awaitable[None]]
LoggerLike = Any
NormalizeDoc = Callable[[Dict[str, Any]], Dict[str, Any]]
RetrieveVector = Callable[..., Awaitable[tuple[List[Dict[str, Any]], str]]]
RetrieveFulltext = Callable[[str, Sequence[str], int], List[Dict[str, Any]]]
RankFusion = Callable[..., List[Dict[str, Any]]]
RetryableErrorChecker = Callable[[Exception], bool]


async def run_hybrid_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
    logger: LoggerLike,
    safe_emit: EmitFunc,
    normalize_doc: NormalizeDoc,
    retrieve_vector_context: RetrieveVector,
    retrieve_context_by_keywords: RetrieveFulltext,
    reciprocal_rank_fusion_func: RankFusion,
    is_retryable_embedding_error: RetryableErrorChecker,
    rrf_k: int,
) -> Dict[str, Any]:
    query_text = query_spec["query"]
    label = query_spec["label"]
    scoped_log_prefix = f"{log_prefix}:{label}"
    status = retrieval_hybrid_search.initial_hybrid_status()

    await safe_emit(
        emit,
        f"[retrieval] retrieving candidate chunks for query: {query_text}",
        query_text,
        "retrieval",
    )

    vector_results, fulltext_results = await asyncio.gather(
        retrieval_hybrid_search.run_vector_search_for_query(
            query_spec,
            selected_file_ids,
            emit,
            retrieval_k=retrieval_k,
            log_prefix=log_prefix,
            scoped_log_prefix=scoped_log_prefix,
            logger=logger,
            safe_emit=safe_emit,
            normalize_doc=normalize_doc,
            retrieve_vector_context=retrieve_vector_context,
            is_retryable_embedding_error=is_retryable_embedding_error,
            status=status,
        ),
        retrieval_hybrid_search.run_fulltext_search_for_query(
            query_spec,
            selected_file_ids,
            emit,
            retrieval_k=retrieval_k,
            log_prefix=log_prefix,
            logger=logger,
            safe_emit=safe_emit,
            normalize_doc=normalize_doc,
            retrieve_context_by_keywords=retrieve_context_by_keywords,
            status=status,
        ),
    )
    fused = reciprocal_rank_fusion_func([vector_results, fulltext_results], k=rrf_k)
    logger.info(
        "[%s] subquery_summary label=%r query=%r kind=%s vector_hits=%s fulltext_hits=%s fused_top_chunk_ids=%s",
        log_prefix,
        label,
        query_text[:160],
        query_spec.get("query_kind"),
        len(vector_results),
        len(fulltext_results),
        [doc.get("chunkId") for doc in fused[:5]],
    )
    return retrieval_hybrid_search.build_hybrid_search_result(
        query_spec,
        vector_results,
        fulltext_results,
        fused,
        status,
    )
