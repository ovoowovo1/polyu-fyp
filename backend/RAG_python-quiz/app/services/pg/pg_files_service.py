# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from app.services.core.exceptions import NotFoundError, ValidationServiceError
from app.services.pg.pg_access_control import (
    can_access_chunk,
    can_access_document,
    require_document_teacher,
)
from app.services.pg.pg_db import fetch_all, map_rows, require_row, with_cursor
from app.utils.datetime_utils import iso


def get_files_list(class_id: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    base_sql = """
    SELECT d.id, d.name, d.size_bytes AS size, d.mimetype AS mime_type,
           d.created_at AS upload_date, COUNT(c.id) AS total_chunks
    FROM documents d
    LEFT JOIN chunks c ON c.document_id = d.id
    LEFT JOIN classes cls ON cls.id = d.class_id
    LEFT JOIN class_students cs ON cs.class_id = d.class_id AND cs.student_id = %s
    """
    params = [user_id]
    if class_id:
        base_sql += " WHERE d.class_id = %s\n"
        params.append(class_id)
        if user_id:
            base_sql += " AND (cls.teacher_id = %s OR cs.student_id IS NOT NULL)\n"
            params.append(user_id)
    elif user_id:
        base_sql += " WHERE d.class_id IS NOT NULL AND (cls.teacher_id = %s OR cs.student_id IS NOT NULL)\n"
        params.append(user_id)

    base_sql += " GROUP BY d.id\n    ORDER BY d.created_at DESC\n"

    return map_rows(base_sql, tuple(params), mapper=_format_file_summary)


def delete_file(file_id: str, teacher_id: Optional[str] = None) -> Dict[str, Any]:
    if teacher_id:
        require_document_teacher(teacher_id, file_id)
    with with_cursor(write=True) as cur:
        cur.execute("SELECT id, name FROM documents WHERE id=%s", (file_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("File not found")
        name = row["name"]
        cur.execute("DELETE FROM documents WHERE id=%s", (file_id,))
        return {
            "message": f"File '{name}' deleted",
            "deletedFile": {"id": str(row["id"]), "name": name},
        }


def rename_file(file_id: str, new_name: str, teacher_id: Optional[str] = None) -> Dict[str, Any]:
    if teacher_id:
        require_document_teacher(teacher_id, file_id)
    row = require_row(
        "UPDATE documents SET name=%s WHERE id=%s RETURNING id, name",
        (new_name, file_id),
        error=NotFoundError("File not found"),
        write=True,
    )
    return {
        "message": f"File renamed to '{new_name}'",
        "renamedFile": {"id": str(row["id"]), "name": row["name"]},
    }


def get_specific_file(file_id: str, user_id: Optional[str] = None) -> dict:
    if user_id and not can_access_document(user_id, file_id):
        raise NotFoundError("File not found")
    sql_file = "SELECT id, name, size_bytes, mimetype, created_at FROM documents WHERE id=%s"
    sql_chunks = """
    SELECT id, text AS content, page_start, page_end, chunk_index
    FROM chunks
    WHERE document_id=%s
    ORDER BY chunk_index ASC
    """
    f = require_row(sql_file, (file_id,), error=NotFoundError("File not found"))
    chunks = fetch_all(sql_chunks, (file_id,))
    formatted_file = _format_file_detail(f, total_chunks=len(chunks))
    formatted_chunks = [
        {
            "id": str(c["id"]),
            "content": c["content"],
            "chunk_index": c["chunk_index"],
        }
        for c in chunks
    ]
    return {"file": formatted_file, "chunks": formatted_chunks}


def get_source_details_by_chunk_id(chunk_id: str, user_id: Optional[str] = None) -> dict:
    if user_id and not can_access_chunk(user_id, chunk_id):
        raise NotFoundError("Chunk not found")
    sql = """
    SELECT d.id AS file_id, d.name AS source_file,
           c.page_start, c.page_end, c.chunk_index, c.id AS chunk_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = %s
    """
    r = require_row(sql, (chunk_id,), error=NotFoundError("Chunk not found"))
    return {
        "file_id": str(r["file_id"]),
        "page_number": r["page_start"],
        "source_index": int(r["chunk_index"]),
        "source_file": r["source_file"],
        "file_chunk_id": str(r["chunk_id"]),
    }


def get_files_text_content(file_ids: list[str]) -> str:
    if not file_ids:
        raise ValidationServiceError("File id list cannot be empty")
    sql = """
    SELECT d.name AS file_name, c.text AS text, c.chunk_index
    FROM documents d
    JOIN chunks c ON c.document_id = d.id
    WHERE d.id = ANY(%s::uuid[])
    ORDER BY d.name ASC, c.chunk_index ASC
    """
    rows = fetch_all(sql, (file_ids,))
    parts, current = [], None
    for r in rows:
        if current != r["file_name"]:
            current = r["file_name"]
            parts.append(f"\n\n=== {current} ===\n")
        parts.append(r["text"])
    if not parts:
        raise ValidationServiceError("Specified files were not found or contain no text")
    return "\n\n".join(parts)


def _format_file_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "filename": row["name"],
        "original_name": row["name"],
        "file_size": row["size"],
        "mime_type": row["mime_type"],
        "upload_date": iso(row["upload_date"]),
        "status": "completed",
        "total_chunks": int(row["total_chunks"]),
    }


def _format_file_detail(row: Dict[str, Any], *, total_chunks: int) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "filename": row["name"],
        "original_name": row["name"],
        "file_size": str(row["size_bytes"]) if row["size_bytes"] is not None else None,
        "mime_type": row["mimetype"],
        "upload_date": iso(row["created_at"]),
        "status": "completed",
        "total_chunks": total_chunks,
    }


__all__ = [
    "delete_file",
    "get_files_list",
    "get_files_text_content",
    "get_source_details_by_chunk_id",
    "get_specific_file",
    "rename_file",
]
