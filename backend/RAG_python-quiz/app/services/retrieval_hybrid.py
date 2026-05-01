from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from app.services.retrieval_intent import QuerySearchSpec

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
    vector_failed = False
    vector_retrieval_degraded = False
    fulltext_failed = False
    retrieval_mode = "primary"

    await safe_emit(
        emit,
        f"[retrieval] retrieving candidate chunks for query: {query_text}",
        query_text,
        "retrieval",
    )

    async def run_vector_search() -> List[Dict[str, Any]]:
        nonlocal vector_failed, vector_retrieval_degraded, retrieval_mode

        try:
            rows, retrieval_mode = await retrieve_vector_context(
                query_text,
                selected_file_ids,
                k=retrieval_k,
                log_prefix=scoped_log_prefix,
            )
            await safe_emit(
                emit,
                f"[retrieval] vector search completed with {len(rows)} hits ({retrieval_mode}) for {label}.",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] vector_search label=%r query=%r hits=%s mode=%s top_chunk_ids=%s",
                log_prefix,
                label,
                query_text[:160],
                len(rows),
                retrieval_mode,
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [normalize_doc(row) for row in rows]
        except Exception as err:
            vector_failed = True
            vector_retrieval_degraded = is_retryable_embedding_error(err)
            logger.warning("[%s] vector retrieval failed for %r: %s", log_prefix, label, err)
            await safe_emit(
                emit,
                f"[retrieval] vector search failed for {label}: {err}",
                0,
                "retrieval",
            )
            return []

    async def run_fulltext_search() -> List[Dict[str, Any]]:
        nonlocal fulltext_failed

        try:
            rows = await asyncio.to_thread(
                retrieve_context_by_keywords,
                query_text,
                selected_file_ids,
                retrieval_k,
            )
            await safe_emit(
                emit,
                f"[retrieval] fulltext search completed with {len(rows)} hits for {label}.",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] fulltext_search label=%r query=%r hits=%s top_chunk_ids=%s",
                log_prefix,
                label,
                query_text[:160],
                len(rows),
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [normalize_doc(row) for row in rows]
        except Exception as err:
            fulltext_failed = True
            logger.warning("[%s] fulltext retrieval failed for %r: %s", log_prefix, label, err)
            await safe_emit(
                emit,
                f"[retrieval] fulltext search failed for {label}: {err}",
                0,
                "retrieval",
            )
            return []

    vector_results, fulltext_results = await asyncio.gather(
        run_vector_search(),
        run_fulltext_search(),
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
    return {
        "query_spec": query_spec,
        "vector_results": vector_results,
        "fulltext_results": fulltext_results,
        "fused": fused,
        "vector_failed": vector_failed,
        "fulltext_failed": fulltext_failed,
        "vector_retrieval_degraded": vector_retrieval_degraded,
        "retrieval_mode": retrieval_mode,
    }
