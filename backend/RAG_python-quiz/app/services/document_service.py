# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional
import asyncio
import hashlib

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.logger import get_logger
from app.services import pg_service
from app.services.progress_bus import publish_progress
from app.services.crawler import load_markdown
from app.utils.api_key_manager import create_embedding_model
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError
from app.utils.pdf_utils import extract_text_by_page

logger = get_logger(__name__)


INITIAL_EMBED_BATCH_SIZE = 30
EMBED_RETRY_ATTEMPTS = 3
EMBED_RETRY_DELAYS = (0.5, 1.0)
EMBED_SPLIT_DELAY = 2.0

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=400)


def _is_pdf_upload(filename: str, mimetype: str) -> bool:
    normalized_type = (mimetype or "").lower()
    normalized_name = (filename or "").lower()
    return normalized_type == "application/pdf" or normalized_name.endswith(".pdf")


def _coerce_embedding_error(
    error: Exception,
    *,
    model_name: str,
    base_url: str,
) -> EmbeddingProviderError:
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


async def _embed_batch_with_adaptive_retry(
    texts: List[str],
    embeddings_model,
    *,
    batch_label: str,
) -> List[List[float]]:
    last_error: Optional[EmbeddingProviderError] = None

    for attempt in range(1, EMBED_RETRY_ATTEMPTS + 1):
        logger.info(
            "[Ingest] Embedding batch %s attempt %s/%s (size=%s)",
            batch_label,
            attempt,
            EMBED_RETRY_ATTEMPTS,
            len(texts),
        )
        try:
            return await embeddings_model.aembed_documents(texts)
        except Exception as err:
            last_error = _coerce_embedding_error(
                err,
                model_name=embeddings_model.model_name,
                base_url=embeddings_model.base_url,
            )
            logger.warning(
                "[Ingest] Embedding batch %s attempt %s/%s failed: %s",
                batch_label,
                attempt,
                EMBED_RETRY_ATTEMPTS,
                last_error,
            )

            if not last_error.retryable:
                raise last_error

            if attempt < EMBED_RETRY_ATTEMPTS:
                await asyncio.sleep(EMBED_RETRY_DELAYS[attempt - 1])

    if last_error is None:
        raise RuntimeError("Embedding batch failed without an error")

    if len(texts) == 1:
        raise last_error

    await asyncio.sleep(EMBED_SPLIT_DELAY)
    mid = len(texts) // 2
    logger.warning(
        "[Ingest] Embedding batch %s exhausted retries; splitting %s -> %s + %s",
        batch_label,
        len(texts),
        mid,
        len(texts) - mid,
    )
    left = await _embed_batch_with_adaptive_retry(
        texts[:mid],
        embeddings_model,
        batch_label=f"{batch_label}.1",
    )
    right = await _embed_batch_with_adaptive_retry(
        texts[mid:],
        embeddings_model,
        batch_label=f"{batch_label}.2",
    )
    return left + right


async def embed_texts_with_retry(
    texts: List[str],
    *,
    embeddings_model=None,
) -> List[List[float]]:
    if not texts:
        return []

    if embeddings_model is None:
        embeddings_model = create_embedding_model()
    all_vectors: List[List[float]] = []

    logger.info("[Ingest] Starting adaptive embedding generation")

    for start in range(0, len(texts), INITIAL_EMBED_BATCH_SIZE):
        batch_texts = texts[start : start + INITIAL_EMBED_BATCH_SIZE]
        batch_number = start // INITIAL_EMBED_BATCH_SIZE + 1

        vectors = await _embed_batch_with_adaptive_retry(
            batch_texts,
            embeddings_model,
            batch_label=str(batch_number),
        )
        all_vectors.extend(vectors)
        logger.info(
            "[Ingest] Embedding batch %s completed successfully (%s vectors)",
            batch_number,
            len(vectors),
        )

    logger.info("[Ingest] Generated %s vectors in total", len(all_vectors))
    return all_vectors


async def _embed_chunks_with_retry(chunks: List[Dict[str, Any]]) -> List[List[float]]:
    texts = [chunk["pageContent"] for chunk in chunks]
    return await embed_texts_with_retry(texts)


async def _embed_chunks_for_storage(
    chunks: List[Dict[str, Any]],
) -> tuple[List[List[float]], Optional[List[List[float]]]]:
    texts = [chunk["pageContent"] for chunk in chunks]
    primary_model = create_embedding_model()
    primary_vectors = await embed_texts_with_retry(texts, embeddings_model=primary_model)

    settings = get_settings()
    fallback_model_name = settings.openai_embedding_fallback_model
    fallback_column = settings.openai_embedding_fallback_column
    if not fallback_model_name or fallback_column == "embedding":
        return primary_vectors, None

    try:
        fallback_model = create_embedding_model(
            model_name=fallback_model_name,
            base_url=settings.openai_embedding_base_url,
        )
        fallback_vectors = await embed_texts_with_retry(texts, embeddings_model=fallback_model)
        return primary_vectors, fallback_vectors
    except Exception as err:
        logger.warning(
            "[Ingest] Standby embeddings unavailable for column=%s model=%s; continuing with primary only: %s",
            fallback_column,
            fallback_model_name,
            err,
        )
        return primary_vectors, None


def _assemble_chunks_for_db(
    chunks: List[Dict[str, Any]],
    primary_vectors: List[List[float]],
    fallback_vectors: Optional[List[List[float]]] = None,
    *,
    fallback_column: str = "embedding_v2",
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        payload = {
            "text": chunk["pageContent"],
            "metadata": chunk["metadata"],
            "embedding": primary_vectors[index],
        }
        if fallback_column != "embedding":
            payload[fallback_column] = fallback_vectors[index] if fallback_vectors is not None else None
        rows.append(payload)
    return rows


async def ingest_document(
    *,
    filename: str,
    content: bytes,
    size: int,
    mimetype: str,
    client_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Dict[str, Any]:
    del client_id

    logger.info("[Ingest] Starting file processing: %s", filename)

    if not _is_pdf_upload(filename, mimetype):
        raise DocumentIngestError(
            code="UNSUPPORTED_MEDIA_TYPE",
            message="Only PDF uploads are supported.",
            details=f"filename={filename}, mimetype={mimetype or '<empty>'}",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    existing = pg_service.find_document_by_hash(file_hash)
    if existing:
        logger.info("[Ingest] Duplicate file detected: %s", filename)
        return {
            "message": "File already exists. Reusing the existing document.",
            "fileId": existing["id"],
            "isNew": False,
            "chunksCount": 0,
            "entitiesCount": 0,
            "relationshipsCount": 0,
        }

    try:
        pages_text = await extract_text_by_page(content)
    except Exception as err:
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to extract text from the PDF.",
            details=str(err),
        ) from err

    docs = [
        {"pageContent": text, "metadata": {"source": filename, "pageNumber": page_number}}
        for page_number, text in enumerate(pages_text, start=1)
        if text.strip() and len(text.strip()) > 10
    ]
    if not docs:
        raise DocumentIngestError(
            code="EMPTY_DOCUMENT",
            message="No extractable text was found in this PDF.",
        )

    chunks: List[Dict[str, Any]] = []
    for doc in docs:
        for chunk in text_splitter.split_text(doc["pageContent"]):
            chunks.append({"pageContent": chunk, "metadata": doc["metadata"]})

    logger.info("[Ingest] Document split into %s chunks", len(chunks))

    try:
        primary_vectors, fallback_vectors = await _embed_chunks_for_storage(chunks)
    except EmbeddingProviderError:
        raise
    except Exception as err:
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to generate embeddings for this document.",
            details=str(err),
        ) from err
    chunks_for_db = _assemble_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        fallback_column=get_settings().openai_embedding_fallback_column,
    )
    document_data = {
        "name": filename,
        "size": size,
        "hash": file_hash,
        "mimetype": mimetype or "application/pdf",
    }
    if class_id:
        document_data["class_id"] = class_id

    try:
        result = pg_service.create_graph_from_document(document_data, chunks_for_db)
    except Exception as err:
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to store the document in the database.",
            details=str(err),
        ) from err

    logger.info("[Ingest] File processing completed successfully: %s", filename)
    return {
        "message": f"Uploaded {filename}",
        "fileId": result["fileId"],
        "chunksCount": len(chunks),
        "entitiesCount": 0,
        "relationshipsCount": 0,
        "isNew": True,
    }


async def ingest_website(
    *,
    url: str,
    client_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Dict[str, Any]:
    logger.info("[Ingest] Starting website processing: %s", url)

    docs_markdown = await load_markdown(url)
    if not docs_markdown:
        raise RuntimeError("Fetched website content was empty.")

    markdown = "\n\n".join(
        (getattr(doc, "page_content", "") or "") for doc in docs_markdown
    ).strip()
    if not markdown:
        raise RuntimeError("Fetched website content was empty.")

    size = len(markdown.encode("utf-8"))
    file_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    existing = pg_service.find_document_by_hash(file_hash)
    if existing:
        logger.info("[Ingest] Duplicate website detected: %s", url)
        return {
            "message": "Website already exists. Reusing the existing document.",
            "fileId": existing["id"],
            "isNew": False,
        }

    parts = text_splitter.split_text(markdown)
    chunks = [
        {"pageContent": part, "metadata": {"source": url, "pageNumber": index + 1}}
        for index, part in enumerate(parts)
    ]

    total_tasks = len(chunks)
    total_with_db = total_tasks + 1
    await publish_progress(client_id, {"type": "progress", "done": 0, "total": total_with_db})

    primary_vectors, fallback_vectors = await _embed_chunks_for_storage(chunks)

    chunks_for_db = _assemble_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        fallback_column=get_settings().openai_embedding_fallback_column,
    )
    document_data = {
        "name": url,
        "size": size,
        "hash": file_hash,
        "mimetype": "text/markdown",
    }
    if class_id:
        document_data["class_id"] = class_id

    result = pg_service.create_graph_from_document(document_data, chunks_for_db)

    await publish_progress(client_id, {"type": "progress", "done": total_with_db, "total": total_with_db})
    await publish_progress(
        client_id,
        {"type": "finished", "status": "success", "fileId": result["fileId"], "chunks": len(chunks)},
    )

    return {
        "message": f"Uploaded {url}",
        "fileId": result["fileId"],
        "chunksCount": len(chunks),
        "entitiesCount": 0,
        "relationshipsCount": 0,
        "isNew": True,
    }
