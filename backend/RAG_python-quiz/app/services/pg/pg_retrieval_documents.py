# -*- coding: utf-8 -*-
"""Document and chunk write helpers for retrieval storage."""

from typing import Any, Dict, Optional

from app.logger import get_logger
from app.services.core.exceptions import PermissionDeniedError, ValidationServiceError
from app.services.pg.pg_db import set_rls_user
from app.services.pg.pg_shared import _to_pgvector


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


def build_chunk_rows(doc_id: str, chunks: list[dict]) -> list[tuple]:
    rows = []
    for index, chunk in enumerate(chunks):
        meta = chunk.get("metadata") or {}
        page_number = int(meta.get("pageNumber") or 1)
        row = [
            doc_id,
            page_number,
            int(meta.get("pageEnd") or page_number),
            index,
            chunk.get("text") or "",
        ]
        vector = chunk.get("embedding")
        row.append(_to_pgvector(vector) if vector is not None else None)
        rows.append(tuple(row))
    return rows


def insert_chunks(execute_values, cur, rows: list[tuple]) -> None:
    execute_values(
        cur,
        """
        INSERT INTO chunks (document_id, page_start, page_end, chunk_index, text, embedding)
        VALUES %s
        """,
        rows,
        template="(%s,%s,%s,%s,%s,%s::vector)",
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
    user_id: Optional[str] = None,
) -> dict:
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
            rows = build_chunk_rows(doc_id, chunks)
            insert_chunks(execute_values, cur, rows)
            insert_chunk_media(execute_values, cur, doc_id, chunks)
        except Exception as error:
            raise DocumentStorageError("chunks", error) from error

        conn.commit()
        return {"fileId": doc_id, "isNew": True}


def get_reingest_document(*, get_conn, file_id: str, user_id: str) -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT d.id, d.name, d.hash, d.mimetype, d.class_id
            FROM documents d JOIN classes c ON c.id = d.class_id
            WHERE d.id = %s AND c.teacher_id = %s""", (file_id, user_id))
        row = cur.fetchone()
        if not row:
            raise PermissionDeniedError("Only the teacher who owns this document's class can reingest it.")
        return dict(row)


def replace_document_chunks(*, get_conn, execute_values, file_id: str, user_id: str,
                            expected_hash: str, chunks: list[dict]) -> dict:
    if not chunks:
        raise ValidationServiceError("The PDF contains no usable chunks.")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Recheck ownership and hash under the same lock/transaction as the replacement.
            cur.execute("""SELECT d.hash FROM documents d JOIN classes c ON c.id = d.class_id
                WHERE d.id = %s AND c.teacher_id = %s FOR UPDATE OF d, c""", (file_id, user_id))
            row = cur.fetchone()
            if not row:
                raise PermissionDeniedError("Document is unavailable or class ownership changed.")
            if row["hash"] != expected_hash:
                raise ValidationServiceError("Original PDF hash does not match this document.")
            rows = build_chunk_rows(file_id, chunks)
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (file_id,))
            insert_chunks(execute_values, cur, rows)
            insert_chunk_media(execute_values, cur, file_id, chunks)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"fileId": file_id, "chunksCount": len(chunks), "status": "success"}
