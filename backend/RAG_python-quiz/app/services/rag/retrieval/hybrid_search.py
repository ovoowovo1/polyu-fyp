from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from app.services.rag.retrieval.intent import QuerySearchSpec

EventCallback = Callable[[str, Any, str], Awaitable[None]]
EmitFunc = Callable[[EventCallback, str, Any, str], Awaitable[None]]
LoggerLike = Any
NormalizeDoc = Callable[[Dict[str, Any]], Dict[str, Any]]
RetrieveVector = Callable[..., Awaitable[tuple[List[Dict[str, Any]], str]]]
RetrieveFulltext = Callable[[str, Sequence[str], int], List[Dict[str, Any]]]
RetryableErrorChecker = Callable[[Exception], bool]


def initial_hybrid_status() -> Dict[str, Any]:
    return {
        "vector_failed": False,
        "vector_retrieval_degraded": False,
        "fulltext_failed": False,
        "retrieval_mode": "primary",
    }


async def run_vector_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
    scoped_log_prefix: str,
    logger: LoggerLike,
    safe_emit: EmitFunc,
    normalize_doc: NormalizeDoc,
    retrieve_vector_context: RetrieveVector,
    is_retryable_embedding_error: RetryableErrorChecker,
    status: Dict[str, Any],
) -> List[Dict[str, Any]]:
    query_text = query_spec["query"]
    label = query_spec["label"]

    try:
        rows, status["retrieval_mode"] = await retrieve_vector_context(
            query_text,
            selected_file_ids,
            k=retrieval_k,
            log_prefix=scoped_log_prefix,
        )
        await safe_emit(
            emit,
            f"[retrieval] vector search completed with {len(rows)} hits ({status['retrieval_mode']}) for {label}.",
            len(rows),
            "retrieval",
        )
        logger.info(
            "[%s] vector_search label=%r query=%r hits=%s mode=%s top_chunk_ids=%s",
            log_prefix,
            label,
            query_text[:160],
            len(rows),
            status["retrieval_mode"],
            [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
        )
        return [normalize_doc(row) for row in rows]
    except Exception as err:
        status["vector_failed"] = True
        status["vector_retrieval_degraded"] = is_retryable_embedding_error(err)
        logger.warning("[%s] vector retrieval failed for %r: %s", log_prefix, label, err)
        await safe_emit(
            emit,
            f"[retrieval] vector search failed for {label}: {err}",
            0,
            "retrieval",
        )
        return []


async def run_fulltext_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
    logger: LoggerLike,
    safe_emit: EmitFunc,
    normalize_doc: NormalizeDoc,
    retrieve_context_by_keywords: RetrieveFulltext,
    status: Dict[str, Any],
) -> List[Dict[str, Any]]:
    query_text = query_spec["query"]
    label = query_spec["label"]

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
        status["fulltext_failed"] = True
        logger.warning("[%s] fulltext retrieval failed for %r: %s", log_prefix, label, err)
        await safe_emit(
            emit,
            f"[retrieval] fulltext search failed for {label}: {err}",
            0,
            "retrieval",
        )
        return []


def build_hybrid_search_result(
    query_spec: QuerySearchSpec,
    vector_results: List[Dict[str, Any]],
    fulltext_results: List[Dict[str, Any]],
    fused: List[Dict[str, Any]],
    status: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "query_spec": query_spec,
        "vector_results": vector_results,
        "fulltext_results": fulltext_results,
        "fused": fused,
        "vector_failed": status["vector_failed"],
        "fulltext_failed": status["fulltext_failed"],
        "vector_retrieval_degraded": status["vector_retrieval_degraded"],
        "retrieval_mode": status["retrieval_mode"],
    }
