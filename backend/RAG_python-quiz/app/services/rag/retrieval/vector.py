from __future__ import annotations

import asyncio
from typing import Sequence

from app.config import get_settings
from app.logger import get_logger
from app.services.cache import rag_cache
from app.services.pg import pg_retrieval_service as pg_service
from app.utils.api_key_manager import get_embedding_model
from app.utils.ingest_errors import EmbeddingProviderError

logger = get_logger(__name__)


def is_retryable_embedding_error(error: Exception) -> bool:
    return isinstance(error, EmbeddingProviderError) and error.retryable


async def retrieve_vector_context(question: str, selected_file_ids: Sequence[str], *, k: int = 20,
                                  log_prefix: str = "vector retrieval") -> tuple[list[dict], str]:
    settings = get_settings()
    model = get_embedding_model()
    if model is None:
        raise RuntimeError("Embedding API Key not configured, unable to perform vector retrieval")
    query_text = rag_cache.normalize_query_text(question)
    vector = await rag_cache.get_or_set_query_embedding(model, query_text, settings=settings)

    async def load():
        return await asyncio.to_thread(pg_service.retrieve_graph_context, vector, k, list(selected_file_ids))

    async def rehydrate(rows):
        return await asyncio.to_thread(pg_service.retrieve_context_by_chunk_ids, rows, list(selected_file_ids))

    rows = await rag_cache.get_or_set_retrieval_rows(vector, query_text=query_text,
        selected_file_ids=selected_file_ids, k=k, model=model, settings=settings,
        loader=load, rehydrate=rehydrate)
    logger.info("[%s] model=%s results=%s", log_prefix, model.model_name, len(rows))
    return rows, "single"
