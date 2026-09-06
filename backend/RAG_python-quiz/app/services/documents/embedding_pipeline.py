from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.utils.ingest_errors import EmbeddingProviderError


def coerce_embedding_error(error: Exception, *, model_name: str, base_url: str) -> EmbeddingProviderError:
    if isinstance(error, EmbeddingProviderError):
        return error

    return EmbeddingProviderError(
        code="EMBEDDING_UPSTREAM_FAILED",
        message=f"Embedding request failed unexpectedly: {error}",
        retryable=False,
        provider="openai-compatible",
        model=model_name,
        base_url=base_url,
        upstream_message=str(error),
    )


async def embed_batch_with_adaptive_retry(
    texts: List[str],
    embeddings_model,
    *,
    batch_label: str,
    retry_attempts: int,
    retry_delays: tuple[float, ...],
    split_delay: float,
    sleep,
    logger,
) -> List[List[float]]:
    last_error: Optional[EmbeddingProviderError] = None

    for attempt in range(1, retry_attempts + 1):
        logger.info(
            "[Ingest] Embedding batch %s attempt %s/%s (size=%s)",
            batch_label,
            attempt,
            retry_attempts,
            len(texts),
        )
        try:
            return await embeddings_model.aembed_documents(texts)
        except Exception as err:
            last_error = coerce_embedding_error(
                err,
                model_name=embeddings_model.model_name,
                base_url=embeddings_model.base_url,
            )
            logger.warning(
                "[Ingest] Embedding batch %s attempt %s/%s failed: %s",
                batch_label,
                attempt,
                retry_attempts,
                last_error,
            )
            if not last_error.retryable:
                raise last_error
            if attempt < retry_attempts:
                await sleep(retry_delays[attempt - 1])

    if last_error is None:
        raise RuntimeError("Embedding batch failed without an error")

    if len(texts) == 1:
        raise last_error

    await sleep(split_delay)
    mid = len(texts) // 2
    logger.warning(
        "[Ingest] Embedding batch %s exhausted retries; splitting %s -> %s + %s",
        batch_label,
        len(texts),
        mid,
        len(texts) - mid,
    )
    left = await embed_batch_with_adaptive_retry(
        texts[:mid],
        embeddings_model,
        batch_label=f"{batch_label}.1",
        retry_attempts=retry_attempts,
        retry_delays=retry_delays,
        split_delay=split_delay,
        sleep=sleep,
        logger=logger,
    )
    right = await embed_batch_with_adaptive_retry(
        texts[mid:],
        embeddings_model,
        batch_label=f"{batch_label}.2",
        retry_attempts=retry_attempts,
        retry_delays=retry_delays,
        split_delay=split_delay,
        sleep=sleep,
        logger=logger,
    )
    return left + right


async def embed_chunks_for_storage(
    chunks: List[Dict[str, Any]], *, embed_texts,
) -> List[List[float]]:
    inputs = [chunk.get("embeddingInput", chunk["pageContent"]) for chunk in chunks]
    return await embed_texts(inputs)
