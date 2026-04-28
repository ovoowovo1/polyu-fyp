# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

import psycopg2.extras

from app.services.pg_db import _get_conn
from app.services.pg_shared import _get_embedding_column, _to_pgvector


def find_document_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT id FROM documents WHERE hash=%s"
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (file_hash,))
        row = cur.fetchone()
        return {"id": str(row["id"])} if row else None


def create_graph_from_document(
    document: dict,
    chunks: list[dict],
    *,
    embedding_column: Optional[str] = None,
) -> dict:
    """
    Upsert document, then batch insert chunks using:
    (document_id, page_start, page_end, chunk_index, text, embedding_column)
    - page_start/page_end: from metadata.pageNumber (or 1 if missing)
    - chunk_index: 0-based order within this document
    """
    target_embedding_column = _get_embedding_column(embedding_column)
    insert_columns: list[str]
    if any("embedding_v2" in chunk for chunk in chunks):
        insert_columns = ["embedding", "embedding_v2"]
    else:
        insert_columns = [target_embedding_column]

    with _get_conn() as conn, conn.cursor() as cur:
        # Upsert document. If a class_id is provided, include it in the INSERT.
        if document.get("class_id"):
            cur.execute(
                """
                INSERT INTO documents (hash, name, size_bytes, mimetype, class_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (hash) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """,
                (
                    document.get("hash"),
                    document.get("name"),
                    document.get("size"),
                    document.get("mimetype"),
                    document.get("class_id"),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO documents (hash, name, size_bytes, mimetype)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (hash) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """,
                (
                    document.get("hash"),
                    document.get("name"),
                    document.get("size"),
                    document.get("mimetype"),
                ),
            )
        doc_id = str(cur.fetchone()["id"])

        rows = []
        for i, ch in enumerate(chunks):
            meta = ch.get("metadata") or {}
            pn = int(meta.get("pageNumber") or 1)
            row = [
                doc_id,
                pn,
                pn,
                i,
                ch.get("text") or "",
            ]
            for column_name in insert_columns:
                vector = ch.get(column_name)
                row.append(_to_pgvector(vector) if vector is not None else None)
            rows.append(tuple(row))

        insert_column_sql = ", ".join(insert_columns)
        value_placeholders = ",".join(["%s"] * 5 + ["%s::vector"] * len(insert_columns))

        psycopg2.extras.execute_values(
            cur,
            f"""
            INSERT INTO chunks (document_id, page_start, page_end, chunk_index, text, {insert_column_sql})
            VALUES %s
            """,
            rows,
            template=f"({value_placeholders})",
        )
        conn.commit()
        return {"fileId": doc_id}


def retrieve_graph_context(
    query_vector: list[float],
    k: int = 10,
    selected_file_ids: Optional[list[str]] = None,
    *,
    embedding_column: Optional[str] = None,
) -> list[dict]:
    target_embedding_column = _get_embedding_column(embedding_column)
    vec_txt = _to_pgvector(query_vector)
    null_filter = ""
    if target_embedding_column == "embedding_v2":
        null_filter = f"      c.{target_embedding_column} IS NOT NULL AND\n"
    sql = f"""
    SELECT
      c.text,
      d.name AS source,
      d.id   AS fileId,
      c.page_start,
      c.page_end,
      c.chunk_index,
      c.id   AS chunkId,
      (c.{target_embedding_column} <=> %s::vector) AS score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE (
{null_filter}      (%s::uuid[] IS NULL OR d.id = ANY(%s::uuid[]))
    )
    ORDER BY c.{target_embedding_column} <=> %s::vector
    LIMIT %s
    """
    params = (vec_txt, selected_file_ids or None, selected_file_ids or None, vec_txt, k)
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [
            {
                "text": r["text"],
                "score": float(r["score"]) if r["score"] is not None else None,
                "source": r["source"],
                "page": r["page_start"],
                "fileId": str(r["fileid"]),
                "chunkId": str(r["chunkid"]),
                "mentionedEntities": [],
            }
            for r in rows
        ]


def get_chunks_missing_embeddings(
    *,
    embedding_column: str = "embedding_v2",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    target_embedding_column = _get_embedding_column(embedding_column)
    sql = f"""
    SELECT c.id, c.text
    FROM chunks c
    WHERE c.{target_embedding_column} IS NULL
    ORDER BY c.document_id ASC, c.chunk_index ASC
    LIMIT %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
        return [{"id": str(row["id"]), "text": row["text"]} for row in rows]


def update_chunk_embeddings(
    chunk_vectors: List[Dict[str, Any]],
    *,
    embedding_column: str = "embedding_v2",
) -> int:
    if not chunk_vectors:
        return 0

    target_embedding_column = _get_embedding_column(embedding_column)
    rows = [(item["id"], _to_pgvector(item["embedding"] or [])) for item in chunk_vectors]

    with _get_conn() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"""
            UPDATE chunks AS c
            SET {target_embedding_column} = payload.embedding::vector
            FROM (VALUES %s) AS payload (id, embedding)
            WHERE c.id = payload.id::uuid
            """,
            rows,
            template="(%s,%s)",
        )
        conn.commit()
    return len(rows)


def retrieve_context_by_entities(
    entity_names: List[str], selected_file_ids: List[str] = []
) -> List[Dict[str, Any]]:
    """你已停用圖檢索；為相容保留函式，直接回空。"""
    del entity_names, selected_file_ids
    return []


def retrieve_context_by_keywords(
    keywords: str, selected_file_ids: list[str] = [], k: int = 10
) -> list[dict]:
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        base_sql = """
            SELECT
                c.text,
                paradedb.score(c.id) AS score,
                d.name AS source,
                c.page_start,
                c.document_id AS fileid,
                c.id AS chunkid
            FROM public.chunks AS c
            JOIN public.documents AS d ON d.id = c.document_id
            WHERE c.text @@@ %s
        """
        params = [keywords]

        if selected_file_ids:
            base_sql += " AND c.document_id = ANY(%s::uuid[]) "
            params.append(selected_file_ids)

        base_sql += " ORDER BY score DESC NULLS LAST LIMIT %s "
        params.append(k)

        cur.execute(base_sql, params)
        rows = cur.fetchall()
        return [
            {
                "text": r["text"],
                "score": float(r["score"]) if r["score"] is not None else None,
                "source": r["source"],
                "page": r["page_start"],
                "fileId": str(r["fileid"]),
                "chunkId": str(r["chunkid"]),
                "mentionedEntities": [],
            }
            for r in rows
        ]


__all__ = [
    "create_graph_from_document",
    "find_document_by_hash",
    "get_chunks_missing_embeddings",
    "retrieve_context_by_entities",
    "retrieve_context_by_keywords",
    "retrieve_graph_context",
    "update_chunk_embeddings",
]
