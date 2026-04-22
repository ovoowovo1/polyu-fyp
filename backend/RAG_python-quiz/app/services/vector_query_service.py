from __future__ import annotations

import asyncio
from typing import List, Sequence

from app.config import get_settings
from app.logger import get_logger
from app.services import pg_service
from app.utils.api_key_manager import get_embedding_model, get_fallback_embedding_model
from app.utils.ingest_errors import EmbeddingProviderError

logger = get_logger(__name__)


def is_retryable_embedding_error(error: Exception) -> bool:
    return isinstance(error, EmbeddingProviderError) and error.retryable


async def retrieve_vector_context(
    question: str,
    selected_file_ids: Sequence[str],
    *,
    k: int = 20,
    log_prefix: str = "vector retrieval",
) -> tuple[List[dict], str]:
    settings = get_settings()
    primary_column = settings.embedding_active_column
    fallback_column = settings.embedding_fallback_column
    primary_embeddings = get_embedding_model()

    if primary_embeddings is None:
        raise RuntimeError("Embedding API Key not configured, unable to perform vector retrieval")

    query_text = question.strip()

    try:
        query_vector = await primary_embeddings.aembed_query(query_text)
    except Exception as primary_error:
        if not is_retryable_embedding_error(primary_error):
            raise

        fallback_embeddings = get_fallback_embedding_model()
        if fallback_embeddings is None:
            raise

        logger.warning(
            "[%s] primary embedding failed, retrying with fallback model=%s column=%s: %s",
            log_prefix,
            fallback_embeddings.model_name,
            fallback_column,
            primary_error,
        )

        try:
            fallback_vector = await fallback_embeddings.aembed_query(query_text)
        except Exception as fallback_error:
            if is_retryable_embedding_error(fallback_error):
                logger.error(
                    "[%s] both embedding models failed. primary_model=%s fallback_model=%s primary_error=%s fallback_error=%s",
                    log_prefix,
                    primary_embeddings.model_name,
                    fallback_embeddings.model_name,
                    primary_error,
                    fallback_error,
                )
            raise

        fallback_results = await asyncio.to_thread(
            pg_service.retrieve_graph_context,
            fallback_vector,
            k,
            list(selected_file_ids),
            embedding_column=fallback_column,
        )
        logger.info(
            "[%s] fallback succeeded with model=%s column=%s results=%s",
            log_prefix,
            fallback_embeddings.model_name,
            fallback_column,
            len(fallback_results),
        )
        return fallback_results, "fallback"

    primary_results = await asyncio.to_thread(
        pg_service.retrieve_graph_context,
        query_vector,
        k,
        list(selected_file_ids),
        embedding_column=primary_column,
    )
    logger.info(
        "[%s] primary succeeded with model=%s column=%s results=%s",
        log_prefix,
        primary_embeddings.model_name,
        primary_column,
        len(primary_results),
    )
    return primary_results, "primary"
