# -*- coding: utf-8 -*-
"""Vector retrieval and embedding backfill helpers."""

import base64
from typing import Any, Dict, List, Optional

from app.services.pg.pg_shared import _get_embedding_column, _to_pgvector


def map_context_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "text": row["text"],
        "score": float(row.get("score")) if row.get("score") is not None else None,
        "source": row["source"],
        "page": row["page_start"],
        "fileId": str(row["fileid"]),
        "chunkId": str(row["chunkid"]),
        "mentionedEntities": [],
    }
    image_data = row.get("image_data")
    if image_data:
        if isinstance(image_data, memoryview):
            image_data = image_data.tobytes()
        if isinstance(image_data, bytes):
            image_data = base64.b64encode(image_data).decode("ascii")
        mimetype = row.get("image_mimetype") or "image/png"
        result["image_data"] = f"data:{mimetype};base64,{image_data}"
        result["image_mimetype"] = mimetype
    return result


def retrieve_graph_context(
    *,
    get_conn,
    query_vector: list[float],
    k: int = 10,
    selected_file_ids: Optional[list[str]] = None,
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
      media.data AS image_data,
      media.mimetype AS image_mimetype,
      (c.{target_embedding_column} <=> %s::vector) AS score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    LEFT JOIN chunk_media media ON media.chunk_id = c.id
    WHERE (
{null_filter}      (%s::uuid[] IS NULL OR d.id = ANY(%s::uuid[]))
    )
    ORDER BY c.{target_embedding_column} <=> %s::vector
    LIMIT %s
    """
    params = (vec_txt, selected_file_ids or None, selected_file_ids or None, vec_txt, k)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [map_context_row(row) for row in cur.fetchall()]


def retrieve_context_by_chunk_ids(
    *,
    get_conn,
    cached_rows: list[dict],
) -> list[dict]:
    """Hydrate cached retrieval metadata while preserving cached rank and score."""
    chunk_ids = [str(item["chunkId"]) for item in cached_rows]
    if not chunk_ids:
        return []

    sql = """
    SELECT
      c.text,
      d.name AS source,
      d.id   AS fileId,
      c.page_start,
      c.page_end,
      c.chunk_index,
      c.id   AS chunkId,
      media.data AS image_data,
      media.mimetype AS image_mimetype,
      NULL AS score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    LEFT JOIN chunk_media media ON media.chunk_id = c.id
    WHERE c.id = ANY(%s::uuid[])
    """

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (chunk_ids,))
        rows_by_id = {
            str(row["chunkid"]): map_context_row(row)
            for row in cur.fetchall()
        }

    hydrated = []
    for cached_row in cached_rows:
        chunk_id = str(cached_row["chunkId"])
        row = rows_by_id.get(chunk_id)
        if row is None:
            continue
        row["score"] = cached_row["score"]
        hydrated.append(row)
    return hydrated


def get_chunks_missing_embeddings(
    *,
    get_conn,
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
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return [{"id": str(row["id"]), "text": row["text"]} for row in cur.fetchall()]


def update_chunk_embeddings(
    *,
    get_conn,
    execute_values,
    chunk_vectors: List[Dict[str, Any]],
    embedding_column: str = "embedding_v2",
) -> int:
    if not chunk_vectors:
        return 0

    target_embedding_column = _get_embedding_column(embedding_column)
    rows = [(item["id"], _to_pgvector(item["embedding"] or [])) for item in chunk_vectors]

    with get_conn() as conn, conn.cursor() as cur:
        execute_values(
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
