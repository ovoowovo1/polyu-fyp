# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

import psycopg2.extras

from app.config import get_settings
from app.services.cache import redis_cache, studio_cache
from app.services.pg.pg_db import _get_conn
from app.services.pg import pg_retrieval_documents, pg_retrieval_keywords, pg_retrieval_vectors


FULLTEXT_SEARCH_BACKENDS = {"pg_search", "postgres"}


def _get_fulltext_search_backend() -> str:
    backend = getattr(get_settings(), "fulltext_search_backend", "pg_search")
    if backend not in FULLTEXT_SEARCH_BACKENDS:
        raise ValueError(f"Unsupported fulltext search backend: {backend}")
    return backend


def find_document_by_hash(
    file_hash: str,
    class_id: Optional[str],
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return pg_retrieval_documents.find_document_by_hash(
        lambda: _get_conn(user_id),
        file_hash,
        class_id,
    )


def create_graph_from_document(
    document: dict,
    chunks: list[dict],
    *,
    embedding_column: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """
    Upsert document, then batch insert chunks using:
    (document_id, page_start, page_end, chunk_index, text, embedding_column)
    - page_start/page_end: from metadata.pageNumber (or 1 if missing)
    - chunk_index: 0-based order within this document
    """
    return pg_retrieval_documents.create_graph_from_document(
        get_conn=lambda: _get_conn(user_id),
        execute_values=psycopg2.extras.execute_values,
        document=document,
        chunks=chunks,
        embedding_column=embedding_column,
        user_id=user_id,
    )


def retrieve_graph_context(
    query_vector: list[float],
    k: int = 10,
    selected_file_ids: Optional[list[str]] = None,
    *,
    embedding_column: Optional[str] = None,
) -> list[dict]:
    return pg_retrieval_vectors.retrieve_graph_context(
        get_conn=_get_conn,
        query_vector=query_vector,
        k=k,
        selected_file_ids=selected_file_ids,
        embedding_column=embedding_column,
    )


def get_chunks_missing_embeddings(
    *,
    embedding_column: str = "embedding_v2",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return pg_retrieval_vectors.get_chunks_missing_embeddings(
        get_conn=_get_conn,
        embedding_column=embedding_column,
        limit=limit,
    )


def update_chunk_embeddings(
    chunk_vectors: List[Dict[str, Any]],
    *,
    embedding_column: str = "embedding_v2",
) -> int:
    updated = pg_retrieval_vectors.update_chunk_embeddings(
        get_conn=_get_conn,
        execute_values=psycopg2.extras.execute_values,
        chunk_vectors=chunk_vectors,
        embedding_column=embedding_column,
    )
    if updated:
        redis_cache.invalidate_namespaces(studio_cache.rag_retrieval_namespace())
    return updated


def retrieve_context_by_keywords(
    keywords: str, selected_file_ids: list[str] = [], k: int = 10
) -> list[dict]:
    backend = _get_fulltext_search_backend()
    return pg_retrieval_keywords.retrieve_context_by_keywords(
        get_conn=_get_conn,
        backend=backend,
        keywords=keywords,
        selected_file_ids=selected_file_ids,
        k=k,
    )

