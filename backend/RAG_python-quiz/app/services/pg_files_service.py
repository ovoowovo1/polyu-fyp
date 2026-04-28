# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from app.services.pg_db import _get_conn
from app.utils.datetime_utils import iso


def get_files_list(class_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """等價於原 /files 端點所需的資訊。

    如果傳入 class_id，會僅回傳該班級所屬的文件。
    """
    base_sql = """
    SELECT d.id, d.name, d.size_bytes AS size, d.mimetype AS mime_type,
           d.created_at AS upload_date, COUNT(c.id) AS total_chunks
    FROM documents d
    LEFT JOIN chunks c ON c.document_id = d.id
    """
    params = []
    if class_id:
        base_sql += " WHERE d.class_id = %s\n"
        params.append(class_id)

    base_sql += " GROUP BY d.id\n    ORDER BY d.created_at DESC\n"

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(base_sql, tuple(params) if params else None)
        rows = cur.fetchall()
        return [
            {
                "id": str(r["id"]),
                "filename": r["name"],
                "original_name": r["name"],
                "file_size": r["size"],
                "mime_type": r["mime_type"],
                "upload_date": iso(r["upload_date"]),
                "status": "completed",
                "total_chunks": int(r["total_chunks"]),
            }
            for r in rows
        ]


def delete_file(file_id: str) -> Dict[str, Any]:
    """刪除文件及其 chunks（外鍵 ON DELETE CASCADE）"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM documents WHERE id=%s", (file_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("檔案不存在")
        name = row["name"]
        cur.execute("DELETE FROM documents WHERE id=%s", (file_id,))
        conn.commit()
        return {
            "message": f"檔案 '{name}' 已成功從資料庫刪除。",
            "deletedFile": {"id": str(row["id"]), "name": name},
        }


def rename_file(file_id: str, new_name: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET name=%s WHERE id=%s RETURNING id, name",
            (new_name, file_id),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("檔案不存在")
        return {
            "message": f"檔案已成功重命名為 '{new_name}'",
            "renamedFile": {"id": str(row["id"]), "name": row["name"]},
        }


def get_specific_file(file_id: str) -> dict:
    sql_file = "SELECT id, name, size_bytes, mimetype, created_at FROM documents WHERE id=%s"
    sql_chunks = """
    SELECT id, text AS content, page_start, page_end, chunk_index
    FROM chunks
    WHERE document_id=%s
    ORDER BY chunk_index ASC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql_file, (file_id,))
        f = cur.fetchone()
        if not f:
            raise RuntimeError("檔案不存在")
        cur.execute(sql_chunks, (file_id,))
        chunks = cur.fetchall()
        formatted_file = {
            "id": str(f["id"]),
            "filename": f["name"],
            "original_name": f["name"],
            "file_size": str(f["size_bytes"]) if f["size_bytes"] is not None else None,
            "mime_type": f["mimetype"],
            "upload_date": iso(f["created_at"]),
            "status": "completed",
            "total_chunks": len(chunks),
        }
        formatted_chunks = [
            {
                "id": str(c["id"]),
                "content": c["content"],
                "chunk_index": c["chunk_index"],
            }
            for c in chunks
        ]
        return {"file": formatted_file, "chunks": formatted_chunks}


def get_source_details_by_chunk_id(chunk_id: str) -> dict:
    sql = """
    SELECT d.id AS file_id, d.name AS source_file,
           c.page_start, c.page_end, c.chunk_index, c.id AS chunk_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (chunk_id,))
        r = cur.fetchone()
        if not r:
            raise RuntimeError("找不到 chunk")
        return {
            "file_id": str(r["file_id"]),
            "page_number": r["page_start"],
            "source_index": int(r["chunk_index"]),
            "source_file": r["source_file"],
            "file_chunk_id": str(r["chunk_id"]),
        }


def get_files_text_content(file_ids: list[str]) -> str:
    if not file_ids:
        raise RuntimeError("文件 ID 列表不能為空")
    sql = """
    SELECT d.name AS file_name, c.text AS text, c.chunk_index
    FROM documents d
    JOIN chunks c ON c.document_id = d.id
    WHERE d.id = ANY(%s::uuid[])
    ORDER BY d.name ASC, c.chunk_index ASC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (file_ids,))
        rows = cur.fetchall()
        parts, current = [], None
        for r in rows:
            if current != r["file_name"]:
                current = r["file_name"]
                parts.append(f"\n\n=== {current} ===\n")
            parts.append(r["text"])
        if not parts:
            raise RuntimeError("找不到指定文件或文件沒有內容")
        return "\n\n".join(parts)


__all__ = [
    "delete_file",
    "get_files_list",
    "get_files_text_content",
    "get_source_details_by_chunk_id",
    "get_specific_file",
    "rename_file",
]
