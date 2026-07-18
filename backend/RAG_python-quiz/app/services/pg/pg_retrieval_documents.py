# -*- coding: utf-8 -*-
"""Document and chunk write helpers for retrieval storage."""

from typing import Any, Dict, Optional

from app.logger import get_logger
from app.services.pg.pg_db import set_rls_user
from app.services.pg.pg_shared import _get_embedding_column, _to_pgvector


logger = get_logger(__name__)


class DocumentStorageError(RuntimeError):
    """Marks the database write stage without exposing database details to clients."""

    def __init__(self, stage: str, cause: Exception):
        self.stage = stage
        self.cause = cause
        super().__init__(f"Document storage failed at stage={stage}")


def _safe_postgres_diagnostics(error: Exception) -> dict[str, Optional[str]]:
    """Return only database metadata that is safe for backend diagnostic logs."""
    diagnostics = getattr(error, "diag", None)
    return {
        "sqlstate": getattr(error, "pgcode", None),
        "schema": getattr(diagnostics, "schema_name", None),
        "table": getattr(diagnostics, "table_name", None),
        "constraint": getattr(diagnostics, "constraint_name", None),
        "message": getattr(diagnostics, "message_primary", None),
    }


def find_document_by_hash(get_conn, file_hash: str, class_id: Optional[str]) -> Optional[Dict[str, Any]]:
    sql = "SELECT id FROM documents WHERE hash=%s AND class_id IS NOT DISTINCT FROM %s"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (file_hash, class_id))
        row = cur.fetchone()
        return {"id": str(row["id"])} if row else None


def insert_document(cur, document: dict) -> tuple[str, bool]:
    if document.get("class_id"):
        cur.execute(
            """
            INSERT INTO documents (hash, name, size_bytes, mimetype, class_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (class_id, hash) DO NOTHING
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
        row = cur.fetchone()
        if row:
            return str(row["id"]), True

        cur.execute(
            "SELECT id FROM documents WHERE hash=%s AND class_id=%s",
            (document.get("hash"), document.get("class_id")),
        )
        existing = cur.fetchone()
        if existing:
            return str(existing["id"]), False
        raise RuntimeError("Document conflict could not be read through the RLS policy.")
    else:
        cur.execute(
            """
            INSERT INTO documents (hash, name, size_bytes, mimetype)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (
                document.get("hash"),
                document.get("name"),
                document.get("size"),
                document.get("mimetype"),
            ),
        )
        return str(cur.fetchone()["id"]), True


def verify_document_write_context(cur, *, user_id: Optional[str], class_id: str) -> None:
    """Re-bind and verify the RLS context immediately before a document write."""
    set_rls_user(cur, user_id)
    cur.execute(
        """
        SELECT
            current_setting('app.user_id', true) AS session_user_id,
            app_security.can_manage_document_class(%s::uuid) AS can_manage
        """,
        (class_id,),
    )
    context = cur.fetchone() or {}
    session_user_id = context.get("session_user_id")
    can_manage = bool(context.get("can_manage"))
    logger.info(
        "[Ingest] Document write RLS context class_id=%s requested_user_id=%s session_user_id=%s can_manage=%s",
        class_id,
        user_id,
        session_user_id,
        can_manage,
    )
    if (user_id and session_user_id != str(user_id)) or not can_manage:
        raise PermissionError("Document write RLS context does not authorize this class.")


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


def insert_chunk_media(execute_values, cur, document_id: str, chunks: list[dict]) -> None:
    media_chunks = [
        (index, chunk)
        for index, chunk in enumerate(chunks)
        if chunk.get("image_data") is not None
    ]
    if not media_chunks:
        return

    cur.execute(
        "SELECT id, chunk_index FROM chunks WHERE document_id=%s ORDER BY chunk_index",
        (document_id,),
    )
    chunk_ids = {int(row["chunk_index"]): str(row["id"]) for row in cur.fetchall()}
    rows = []
    for index, chunk in media_chunks:
        chunk_id = chunk_ids.get(index)
        if not chunk_id:
            raise RuntimeError(f"Inserted media chunk could not be found for chunk_index={index}.")
        rows.append(
            (
                chunk_id,
                chunk.get("image_mimetype") or "image/png",
                chunk["image_data"],
            )
        )

    execute_values(
        cur,
        """
        INSERT INTO chunk_media (chunk_id, mimetype, data)
        VALUES %s
        ON CONFLICT (chunk_id) DO NOTHING
        """,
        rows,
        template="(%s,%s,%s)",
    )


def create_graph_from_document(
    *,
    get_conn,
    execute_values,
    document: dict,
    chunks: list[dict],
    embedding_column: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    insert_columns = choose_chunk_embedding_columns(chunks, embedding_column)
    with get_conn() as conn, conn.cursor() as cur:
        try:
            if document.get("class_id"):
                verify_document_write_context(
                    cur,
                    user_id=user_id,
                    class_id=str(document["class_id"]),
                )
            doc_id, is_new = insert_document(cur, document)
        except Exception as error:
            diagnostics = _safe_postgres_diagnostics(error)
            logger.error(
                "[Ingest] Document write failed class_id=%s requested_user_id=%s error_type=%s "
                "sqlstate=%s schema=%s table=%s constraint=%s message=%s",
                document.get("class_id"),
                user_id,
                type(error).__name__,
                diagnostics["sqlstate"],
                diagnostics["schema"],
                diagnostics["table"],
                diagnostics["constraint"],
                diagnostics["message"],
                exc_info=True,
            )
            raise DocumentStorageError("document", error) from error

        if not is_new:
            conn.commit()
            return {"fileId": doc_id, "isNew": False}

        try:
            rows = build_chunk_rows(doc_id, chunks, insert_columns)
            insert_chunks(execute_values, cur, rows, insert_columns)
            insert_chunk_media(execute_values, cur, doc_id, chunks)
        except Exception as error:
            raise DocumentStorageError("chunks", error) from error

        conn.commit()
        return {"fileId": doc_id, "isNew": True}
