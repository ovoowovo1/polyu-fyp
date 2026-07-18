# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional
import asyncio

from langchain_community.document_loaders import AsyncHtmlLoader
from langchain_community.document_transformers import MarkdownifyTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.logger import get_logger
from app.services.documents import document_sources, embedding_pipeline, ingestion_flow, ingestion_payloads
from app.services.pg import pg_retrieval_service as pg_service
from app.services.realtime.progress_bus import publish_progress
from app.utils.api_key_manager import create_embedding_model
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError
from app.utils.pdf_utils import extract_pdf_content_by_page, extract_text_by_page

logger = get_logger(__name__)

INITIAL_EMBED_BATCH_SIZE = 30
EMBED_RETRY_ATTEMPTS = 3
EMBED_RETRY_DELAYS = (0.5, 1.0)
EMBED_SPLIT_DELAY = 2.0

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=400)

async def load_markdown(url: str):
    return await document_sources.load_markdown(
        url,
        loader_cls=AsyncHtmlLoader,
        transformer_cls=MarkdownifyTransformer,
    )


def _is_pdf_upload(filename: str, mimetype: str) -> bool:
    return document_sources.is_pdf_upload(filename, mimetype)


def _is_image_upload(filename: str, mimetype: str) -> bool:
    return document_sources.is_image_upload(filename, mimetype)


def _is_supported_upload(filename: str, mimetype: str) -> bool:
    return document_sources.is_supported_upload(filename, mimetype)


def _coerce_embedding_error(
    error: Exception,
    *,
    model_name: str,
    base_url: str,
) -> EmbeddingProviderError:
    return embedding_pipeline.coerce_embedding_error(error, model_name=model_name, base_url=base_url)


async def _embed_batch_with_adaptive_retry(
    texts: List[str],
    embeddings_model,
    *,
    batch_label: str,
) -> List[List[float]]:
    return await embedding_pipeline.embed_batch_with_adaptive_retry(
        texts,
        embeddings_model,
        batch_label=batch_label,
        retry_attempts=EMBED_RETRY_ATTEMPTS,
        retry_delays=EMBED_RETRY_DELAYS,
        split_delay=EMBED_SPLIT_DELAY,
        sleep=asyncio.sleep,
        logger=logger,
    )


async def embed_texts_with_retry(
    texts: List[Any],
    *,
    embeddings_model=None,
) -> List[List[float]]:
    if not texts:
        return []

    vectors: List[List[float]] = []
    batch: List[Any] = []
    image_count = 0

    async def flush_batch() -> None:
        nonlocal batch, image_count, vectors
        vectors.extend(
            await embedding_pipeline.embed_texts_with_retry(
                batch,
                embeddings_model=embeddings_model,
                create_embedding_model=create_embedding_model,
                initial_batch_size=INITIAL_EMBED_BATCH_SIZE,
                embed_batch=_embed_batch_with_adaptive_retry,
                logger=logger,
            )
        )
        batch = []
        image_count = 0

    for input_value in texts:
        is_image = isinstance(input_value, dict) and "content" in input_value
        if batch and (
            len(batch) >= INITIAL_EMBED_BATCH_SIZE
            or (is_image and image_count >= 6)
        ):
            await flush_batch()
        batch.append(input_value)
        image_count += int(is_image)

    await flush_batch()
    return vectors


async def _embed_chunks_for_storage(
    chunks: List[Dict[str, Any]],
) -> tuple[List[List[float]], Optional[List[List[float]]]]:
    return await embedding_pipeline.embed_chunks_for_storage(
        chunks,
        create_embedding_model=create_embedding_model,
        embed_texts=embed_texts_with_retry,
        get_settings=get_settings,
        logger=logger,
    )


def _assemble_chunks_for_db(
    chunks: List[Dict[str, Any]],
    primary_vectors: List[List[float]],
    fallback_vectors: Optional[List[List[float]]] = None,
    *,
    fallback_column: str = "embedding_v2",
) -> List[Dict[str, Any]]:
    return ingestion_payloads.assemble_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        fallback_column=fallback_column,
    )


async def ingest_document(
    *,
    filename: str,
    content: bytes,
    size: int,
    mimetype: str,
    client_id: Optional[str] = None,
    class_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    del client_id
    return await ingestion_flow.ingest_document(
        filename=filename,
        content=content,
        size=size,
        mimetype=mimetype,
        class_id=class_id,
        user_id=user_id,
        is_pdf_upload=_is_pdf_upload,
        is_supported_upload=_is_supported_upload,
        is_image_upload=_is_image_upload,
        extract_pdf_content_by_page=extract_pdf_content_by_page,
        text_splitter=text_splitter,
        embed_chunks_for_storage=_embed_chunks_for_storage,
        assemble_chunks_for_db=_assemble_chunks_for_db,
        get_settings=get_settings,
        pg_service=pg_service,
        logger=logger,
    )


async def ingest_website(
    *,
    url: str,
    client_id: Optional[str] = None,
    class_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await ingestion_flow.ingest_website(
        url=url,
        client_id=client_id,
        class_id=class_id,
        user_id=user_id,
        load_markdown=load_markdown,
        text_splitter=text_splitter,
        embed_chunks_for_storage=_embed_chunks_for_storage,
        assemble_chunks_for_db=_assemble_chunks_for_db,
        get_settings=get_settings,
        pg_service=pg_service,
        publish_progress=publish_progress,
        logger=logger,
    )
