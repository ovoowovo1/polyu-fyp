# -*- coding: utf-8 -*-
"""Scoped vector retrieval."""

import base64
from typing import Any, Dict, List, Optional

from app.services.pg.pg_shared import _to_pgvector


def map_context_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "text": row["text"],
        "score": float(row.get("score")) if row.get("score") is not None else None,
        "source": row["source"],
        "page": row["page_start"],
        "page_end": row.get("page_end", row["page_start"]),
        "chunk_index": row.get("chunk_index"),
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
) -> list[dict]:
    vec_txt = _to_pgvector(query_vector)
    if not selected_file_ids:
        return []
    null_filter = "      c.embedding IS NOT NULL AND\n"
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
      (c.embedding <=> %s::vector) AS score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    LEFT JOIN chunk_media media ON media.chunk_id = c.id
    WHERE (
{null_filter}      d.id = ANY(%s::uuid[])
      AND app_security.can_access_document(c.document_id)
    )
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
    """
    params = (vec_txt, selected_file_ids, vec_txt, k)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [map_context_row(row) for row in cur.fetchall()]


def retrieve_context_by_chunk_ids(
    *,
    get_conn,
    cached_rows: list[dict],
    selected_file_ids: list[str],
) -> list[dict]:
    """Hydrate cached retrieval metadata while preserving cached rank and score."""
    chunk_ids = [str(item["chunkId"]) for item in cached_rows]
    if not chunk_ids or not selected_file_ids:
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
    WHERE c.id = ANY(%s::uuid[]) AND c.document_id = ANY(%s::uuid[])
      AND app_security.can_access_document(c.document_id)
    """

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (chunk_ids, selected_file_ids))
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


def retrieve_adjacent_chunks(*, get_conn, core: list[dict], selected_file_ids: list[str]) -> list[dict]:
    if not core or not selected_file_ids:
        return []
    sql = """
    SELECT DISTINCT c.text, d.name AS source, d.id AS fileid, c.page_start,
        c.page_end, c.chunk_index, c.id AS chunkid, NULL AS score,
        media.data AS image_data, media.mimetype AS image_mimetype
    FROM chunks anchor
    JOIN chunks c ON c.document_id = anchor.document_id
        AND c.chunk_index BETWEEN anchor.chunk_index - 1 AND anchor.chunk_index + 1
    JOIN documents d ON d.id = c.document_id
    LEFT JOIN chunk_media media ON media.chunk_id = c.id
    WHERE anchor.id = ANY(%s::uuid[]) AND anchor.document_id = ANY(%s::uuid[])
        AND c.document_id = ANY(%s::uuid[])
        AND app_security.can_access_document(c.document_id)
    ORDER BY fileid, chunk_index
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, ([d["chunkId"] for d in core], selected_file_ids, selected_file_ids))
        return [map_context_row(row) for row in cur.fetchall()]
