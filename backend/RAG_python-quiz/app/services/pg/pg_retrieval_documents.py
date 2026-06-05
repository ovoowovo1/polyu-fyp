# -*- coding: utf-8 -*-
"""Document and chunk write helpers for retrieval storage."""

from typing import Any, Dict, Optional

from app.services.pg.pg_shared import _get_embedding_column, _to_pgvector


def find_document_by_hash(get_conn, file_hash: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT id FROM documents WHERE hash=%s"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (file_hash,))
        row = cur.fetchone()
        return {"id": str(row["id"])} if row else None


def insert_document(cur, document: dict) -> str:
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
    return str(cur.fetchone()["id"])


def choose_chunk_embedding_columns(chunks: list[dict], embedding_column: Optional[str] = None) -> list[str]:
    if any("embedding_v2" in chunk for chunk in chunks):
        return ["embedding", "embedding_v2"]
    return [_get_embedding_column(embedding_column)]


def build_chunk_rows(doc_id: str, chunks: list[dict], insert_columns: list[str]) -> list[tuple]:
    rows = []
    for index, chunk in enumerate(chunks):
        meta = chunk.get("metadata") or {}
        page_number = int(meta.get("pageNumber") or 1)
        row = [
            doc_id,
            page_number,
            page_number,
            index,
            chunk.get("text") or "",
        ]
        for column_name in insert_columns:
            vector = chunk.get(column_name)
            row.append(_to_pgvector(vector) if vector is not None else None)
        rows.append(tuple(row))
    return rows


def insert_chunks(execute_values, cur, rows: list[tuple], insert_columns: list[str]) -> None:
    insert_column_sql = ", ".join(insert_columns)
    value_placeholders = ",".join(["%s"] * 5 + ["%s::vector"] * len(insert_columns))
    execute_values(
        cur,
        f"""
        INSERT INTO chunks (document_id, page_start, page_end, chunk_index, text, {insert_column_sql})
        VALUES %s
        """,
        rows,
        template=f"({value_placeholders})",
    )


def create_graph_from_document(
    *,
    get_conn,
    execute_values,
    document: dict,
    chunks: list[dict],
    embedding_column: Optional[str] = None,
) -> dict:
    insert_columns = choose_chunk_embedding_columns(chunks, embedding_column)
    with get_conn() as conn, conn.cursor() as cur:
        doc_id = insert_document(cur, document)
        rows = build_chunk_rows(doc_id, chunks, insert_columns)
        insert_chunks(execute_values, cur, rows, insert_columns)
        conn.commit()
        return {"fileId": doc_id}
