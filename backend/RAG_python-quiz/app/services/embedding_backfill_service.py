from __future__ import annotations

from typing import Any, Dict, Optional

from app.logger import get_logger
from app.services import document_service, pg_service
from app.utils.api_key_manager import create_embedding_model

logger = get_logger(__name__)

DEFAULT_V2_MODEL = "google/gemini-embedding-2-preview"
DEFAULT_TARGET_COLUMN = "embedding_v2"


async def backfill_embedding_column(
    *,
    batch_size: int = document_service.INITIAL_EMBED_BATCH_SIZE,
    limit: Optional[int] = None,
    model_name: str = DEFAULT_V2_MODEL,
    embedding_column: str = DEFAULT_TARGET_COLUMN,
) -> Dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    embeddings_model = create_embedding_model(model_name=model_name)
    remaining = limit
    batches = 0
    updated = 0

    logger.info(
        "[Backfill] Starting embedding backfill for column=%s model=%s batch_size=%s limit=%s",
        embedding_column,
        model_name,
        batch_size,
        limit,
    )

    while remaining is None or remaining > 0:
        current_limit = batch_size if remaining is None else min(batch_size, remaining)
        pending_chunks = pg_service.get_chunks_missing_embeddings(
            embedding_column=embedding_column,
            limit=current_limit,
        )
        if not pending_chunks:
            break

        texts = [chunk["text"] for chunk in pending_chunks]
        vectors = await document_service.embed_texts_with_retry(
            texts,
            embeddings_model=embeddings_model,
        )
        payload = [
            {"id": chunk["id"], "embedding": vectors[index]}
            for index, chunk in enumerate(pending_chunks)
        ]

        updated += pg_service.update_chunk_embeddings(
            payload,
            embedding_column=embedding_column,
        )
        batches += 1
        if remaining is not None:
            remaining -= len(pending_chunks)

        logger.info(
            "[Backfill] Completed batch %s (%s rows updated, remaining=%s)",
            batches,
            len(pending_chunks),
            remaining,
        )

    summary = {
        "embedding_column": embedding_column,
        "model_name": model_name,
        "batch_size": batch_size,
        "batches": batches,
        "updated": updated,
        "limit": limit,
    }
    logger.info("[Backfill] Completed embedding backfill: %s", summary)
    return summary
