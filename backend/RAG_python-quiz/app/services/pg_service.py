# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional, Sequence
import psycopg2
import psycopg2.extras
from datetime import datetime
import json as json_lib
import uuid


from app.config import EmbeddingColumn, get_settings
from app.services.pg_db import _get_conn
from app.utils.datetime_utils import iso


VALID_EMBEDDING_COLUMNS = {"embedding", "embedding_v2"}



# ---- 小工具 ----

def _to_pgvector(vec: Sequence[float]) -> str:
    # 轉成 pgvector 文本字面量，如 "[0.1,0.2,...]"
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def _get_embedding_column(column: Optional[str] = None) -> EmbeddingColumn:
    resolved = column or get_settings().openai_embedding_active_column
    if resolved not in VALID_EMBEDDING_COLUMNS:
        raise ValueError(f"Unsupported embedding column: {resolved}")
    return resolved  # type: ignore[return-value]

# ---- 與 Neo4j 介面一致的函式 ----

def setup_vector_index() -> None:
    """在 Postgres 中不需要像 Neo4j 那樣『建立索引』的 RPC；你應以 migration 建好索引。
    這裡留空，避免呼叫端出錯。"""
    return

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
            cur.execute("""
                INSERT INTO documents (hash, name, size_bytes, mimetype, class_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (hash) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, (document.get("hash"), document.get("name"), document.get("size"), document.get("mimetype"), document.get("class_id")))
        else:
            cur.execute("""
                INSERT INTO documents (hash, name, size_bytes, mimetype)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (hash) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, (document.get("hash"), document.get("name"), document.get("size"), document.get("mimetype")))
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
        return [{
            "text": r["text"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "source": r["source"],
            "page": r["page_start"],              # keep old key name; int for single-page chunks
            "fileId": str(r["fileid"]),
            "chunkId": str(r["chunkid"]),
            "mentionedEntities": [],              # kept for response compatibility
            # (optional extras if you want)
            # "pageEnd": r["page_end"],
            # "chunkIndex": r["chunk_index"],
        } for r in rows]


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
    rows = [
        (item["id"], _to_pgvector(item["embedding"] or []))
        for item in chunk_vectors
    ]

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


def retrieve_context_by_entities(entity_names: List[str], selected_file_ids: List[str] = []) -> List[Dict[str, Any]]:
    """你已停用圖檢索；為相容保留函式，直接回空。"""
    return []

import psycopg2.extras

def retrieve_context_by_keywords(keywords: str, selected_file_ids: list[str] = [], k: int = 10) -> list[dict]:
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

        if selected_file_ids:                         # ← 直接傳字串 list，例如 ['b587...','3af1...']
            base_sql += " AND c.document_id = ANY(%s::uuid[]) "
            params.append(selected_file_ids)

        base_sql += " ORDER BY score DESC NULLS LAST LIMIT %s "
        params.append(k)

        cur.execute(base_sql, params)
        rows = cur.fetchall()
        return [{
            "text": r["text"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "source": r["source"],
            "page": r["page_start"],
            "fileId": str(r["fileid"]),
            "chunkId": str(r["chunkid"]),
            "mentionedEntities": [],
        } for r in rows]



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
        return [{
            "id": str(r["id"]),
            "filename": r["name"],
            "original_name": r["name"],
            "file_size": r["size"],
            "mime_type": r["mime_type"],
            "upload_date": iso(r["upload_date"]),
            "status": "completed",
            "total_chunks": int(r["total_chunks"]),
        } for r in rows]

def delete_file(file_id: str) -> Dict[str, Any]:
    """刪除文件及其 chunks（外鍵 ON DELETE CASCADE）"""
    with _get_conn() as conn, conn.cursor() as cur:
        # 先取名稱用於訊息
        cur.execute("SELECT id, name FROM documents WHERE id=%s", (file_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("檔案不存在")
        name = row["name"]
        cur.execute("DELETE FROM documents WHERE id=%s", (file_id,))
        conn.commit()
        return {"message": f"檔案 '{name}' 已成功從資料庫刪除。", "deletedFile": {"id": str(row["id"]), "name": name}}

def rename_file(file_id: str, new_name: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE documents SET name=%s WHERE id=%s RETURNING id, name", (new_name, file_id))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("檔案不存在")
        return {"message": f"檔案已成功重命名為 '{new_name}'", "renamedFile": {"id": str(row["id"]), "name": row["name"]}}

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
        formatted_chunks = [{
            "id": str(c["id"]),
            "content": c["content"],
            "chunk_index": c["chunk_index"],     # ✅ correct now
            # (optional) "page_start": c["page_start"], "page_end": c["page_end"],
        } for c in chunks]
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
            "page_number": r["page_start"],         # keep old response field name
            "source_index": int(r["chunk_index"]),  # 直接回前算好的 index
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


# ----------------- Quiz -----------------

def _default_quiz_name(cur, file_ids: List[str]) -> str:
    cur.execute("SELECT name FROM documents WHERE id = ANY(%s::uuid[]) LIMIT 3", (file_ids,))
    names = [row["name"] for row in cur.fetchall()]
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - 測驗"
    elif len(names) > 1:
        prefix = f"{len(names)} 個文件的測驗"
    else:
        prefix = "測驗"
    now = datetime.now()
    return f"{prefix} ({now.strftime('%m/%d %H:%M')})"

def save_quiz(quiz_data: Dict[str, Any], file_ids: List[str], quiz_name: str = None, class_id: str = None) -> Dict[str, Any]:
    """保存 Quiz 以及對應文件關聯，結構對齊原實作。"""
    with _get_conn() as conn, conn.cursor() as cur:
        name = quiz_name or _default_quiz_name(cur, file_ids)
        cur.execute("""
            INSERT INTO quizzes (name, questions_json, source_text_length, was_summarized, num_questions, class_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            name,
            json_lib.dumps(quiz_data["questions"]),
            quiz_data.get("source_text_length"),
            quiz_data.get("was_summarized", False),
            len(quiz_data["questions"]),
            class_id,
        ))
        row = cur.fetchone()
        quiz_id = str(row["id"])
        # 關聯到文件
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO quiz_documents (quiz_id, document_id) VALUES %s ON CONFLICT DO NOTHING",
            [(quiz_id, fid) for fid in file_ids],
        )
        conn.commit()
        return {
            "quiz_id": quiz_id,
            "name": name,
            "created_at": int(row["created_at"].timestamp() * 1000) if isinstance(row["created_at"], datetime) else row["created_at"],
            "num_questions": len(quiz_data["questions"]),
        }


def update_quiz(quiz_id: str, quiz_data: Dict[str, Any], name: Optional[str] = None, file_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Update existing quiz's questions and optionally name and linked documents.

    Args:
        quiz_id: UUID of the quiz to update
        quiz_data: dict containing at least 'questions' (list)
        name: optional new name
        file_ids: optional list of document ids to associate (replaces existing associations)

    Returns:
        Dict with updated quiz_id, name and num_questions
    """
    if not quiz_data or "questions" not in quiz_data:
        raise RuntimeError("quiz_data must contain 'questions'")

    with _get_conn() as conn, conn.cursor() as cur:
        # Update main quiz row
        cur.execute(
            """
            UPDATE quizzes
            SET name = COALESCE(%s, name),
                questions_json = %s,
                num_questions = %s
            WHERE id = %s
            RETURNING id, name
            """,
            (
                name,
                json_lib.dumps(quiz_data["questions"]),
                len(quiz_data["questions"]),
                quiz_id,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("測驗不存在")

        # If file_ids provided, replace associations
        if file_ids is not None:
            # remove existing associations for this quiz
            cur.execute("DELETE FROM quiz_documents WHERE quiz_id=%s", (quiz_id,))
            if file_ids:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO quiz_documents (quiz_id, document_id) VALUES %s ON CONFLICT DO NOTHING",
                    [(quiz_id, fid) for fid in file_ids],
                )

        conn.commit()
        return {
            "quiz_id": str(row["id"]),
            "name": row["name"],
            "num_questions": len(quiz_data["questions"]),
        }

def get_all_quizzes(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get quizzes visible to the given user.
    - If user_id is None: return all quizzes (admin/debug use)
    - If user is teacher: return quizzes linked to documents whose class.teacher_id = user_id
    - If user is student: return quizzes linked to documents whose class has the student enrolled
    """
    # SQL to fetch quizzes and their file_ids, filtered by user when provided
    with _get_conn() as conn, conn.cursor() as cur:
        if not user_id:
            base_sql = """
            SELECT q.id, q.name, q.num_questions, q.created_at, q.was_summarized, q.source_text_length,
                   ARRAY_AGG(qd.document_id)::uuid[] AS file_ids
            FROM quizzes q
            LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
            GROUP BY q.id
            ORDER BY q.created_at DESC
            """
            cur.execute(base_sql)
        else:
            # determine if user is teacher
            cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row and row.get("role") else None
            if role == 'teacher':
                # quizzes that have at least one document in classes owned by this teacher
                base_sql = """
                SELECT q.id, q.name, q.num_questions, q.created_at, q.was_summarized, q.source_text_length,
                       ARRAY_AGG(DISTINCT qd.document_id)::uuid[] AS file_ids
                FROM quizzes q
                LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
                LEFT JOIN documents d ON d.id = qd.document_id
                WHERE d.class_id IN (SELECT id FROM classes WHERE teacher_id = %s)
                GROUP BY q.id
                ORDER BY q.created_at DESC
                """
                cur.execute(base_sql, (user_id,))
            else:
                # treat as student (or other): quizzes for classes the student is enrolled in
                base_sql = """
                SELECT q.id, q.name, q.num_questions, q.created_at, q.was_summarized, q.source_text_length,
                       ARRAY_AGG(DISTINCT qd.document_id)::uuid[] AS file_ids
                FROM quizzes q
                LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
                LEFT JOIN documents d ON d.id = qd.document_id
                LEFT JOIN classes c ON c.id = d.class_id
                LEFT JOIN class_students cs ON cs.class_id = c.id
                WHERE cs.student_id = %s
                GROUP BY q.id
                ORDER BY q.created_at DESC
                """
                cur.execute(base_sql, (user_id,))

        rows = cur.fetchall() or []

        # fetch documents names for returned quizzes
        quiz_ids = [r["id"] for r in rows]
        docs = {}
        if quiz_ids:
            sql_docs = """
            SELECT q.id AS quiz_id, d.id AS id, d.name AS name
            FROM quizzes q
            LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
            LEFT JOIN documents d ON d.id = qd.document_id
            WHERE q.id = ANY(%s::uuid[])
            """
            cur.execute(sql_docs, (quiz_ids,))
            for r in cur.fetchall():
                qid = str(r["quiz_id"])
                docs.setdefault(qid, []).append({"id": str(r["id"]) if r["id"] else None, "name": r["name"]})

        quizzes = []
        for r in rows:
            qid = str(r["id"])
            quizzes.append({
                "id": qid,
                "name": r["name"] or "未命名測驗",
                "num_questions": r["num_questions"],
                "created_at": iso(r["created_at"]),
                "file_ids": [str(x) for x in (r["file_ids"] or [])],
                "was_summarized": r["was_summarized"],
                "source_text_length": r["source_text_length"],
                "documents": [d for d in (docs.get(qid) or []) if d.get("id")],
            })
        return quizzes

def get_quizzes_by_class(class_id: str) -> List[Dict[str, Any]]:
    """
    Get quizzes for a specific class.
    """
    # Note: not all installations may have quizzes.class_id column added yet.
    # To be resilient we determine quizzes belonging to a class by the
    # documents linked via quiz_documents -> documents and filter on d.class_id.
    sql = """
    SELECT q.id, q.name, q.num_questions, q.created_at, q.was_summarized, q.source_text_length,
           ARRAY_AGG(DISTINCT qd.document_id)::uuid[] AS file_ids
    FROM quizzes q
    LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
    LEFT JOIN documents d ON d.id = qd.document_id
    WHERE d.class_id = %s
    GROUP BY q.id
    ORDER BY q.created_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (class_id,))
        rows = cur.fetchall() or []

        # fetch documents names for returned quizzes
        quiz_ids = [r["id"] for r in rows]
        docs = {}
        if quiz_ids:
            sql_docs = """
            SELECT q.id AS quiz_id, d.id AS id, d.name AS name
            FROM quizzes q
            LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
            LEFT JOIN documents d ON d.id = qd.document_id
            WHERE q.id = ANY(%s::uuid[])
            """
            cur.execute(sql_docs, (quiz_ids,))
            for r in cur.fetchall():
                qid = str(r["quiz_id"])
                docs.setdefault(qid, []).append({"id": str(r["id"]) if r["id"] else None, "name": r["name"]})

        quizzes = []
        for r in rows:
            qid = str(r["id"])
            quizzes.append({
                "id": qid,
                "name": r["name"] or "未命名測驗",
                "num_questions": r["num_questions"],
                "created_at": iso(r["created_at"]),
                "file_ids": [str(x) for x in (r["file_ids"] or [])],
                "was_summarized": r["was_summarized"],
                "source_text_length": r["source_text_length"],
                "documents": [d for d in (docs.get(qid) or []) if d.get("id")],
            })
        return quizzes

def get_quiz_by_id(quiz_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    sql = """
    SELECT id, name, questions_json, num_questions, created_at, was_summarized, source_text_length
    FROM quizzes WHERE id=%s
    """
    sql_docs = """
    SELECT d.id, d.name, d.class_id
    FROM quiz_documents qd
    JOIN documents d ON d.id = qd.document_id
    WHERE qd.quiz_id=%s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (quiz_id,))
        r = cur.fetchone()
        if not r:
            raise RuntimeError("測驗不存在")

        # fetch associated documents (and their class_id)
        cur.execute(sql_docs, (quiz_id,))
        docs_rows = cur.fetchall()
        documents = [{"id": str(d["id"]), "name": d["name"], "class_id": (str(d["class_id"]) if d.get("class_id") else None)} for d in docs_rows]

        # if user_id provided, enforce access control: teacher who owns the class or student enrolled
        if user_id:
            # check if user is teacher
            cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row and row.get("role") else None
            allowed = False
            if role == 'teacher':
                # teacher may access if they own any class referenced by the quiz
                class_ids = [d["class_id"] for d in documents if d.get("class_id")]
                if class_ids:
                    cur.execute("SELECT 1 FROM classes WHERE id = ANY(%s::uuid[]) AND teacher_id = %s LIMIT 1", (class_ids, user_id))
                    if cur.fetchone():
                        allowed = True
            else:
                # student: may access if enrolled in any class referenced by the quiz
                class_ids = [d["class_id"] for d in documents if d.get("class_id")]
                if class_ids:
                    cur.execute("SELECT 1 FROM class_students WHERE class_id = ANY(%s::uuid[]) AND student_id = %s LIMIT 1", (class_ids, user_id))
                    if cur.fetchone():
                        allowed = True

            if not allowed:
                raise PermissionError("無權訪問此測驗")

        questions = r["questions_json"] or []
        # 可能是 JSONB(已是 list)；也可能是文字（取決於 schema）
        if isinstance(questions, str):
            questions = json_lib.loads(questions)
        return {
            "id": str(r["id"]),
            "name": r["name"] or "未命名測驗",
            "questions": questions,
            "num_questions": r["num_questions"],
            "created_at": iso(r["created_at"]),
            "file_ids": [d["id"] for d in documents],
            "was_summarized": r["was_summarized"],
            "source_text_length": r["source_text_length"],
            "documents": [{"id": d["id"], "name": d["name"]} for d in documents],
        }

def delete_quiz(quiz_id: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM quizzes WHERE id=%s RETURNING id", (quiz_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("測驗不存在")
        return {"message": "測驗已成功刪除", "quiz_id": str(quiz_id)}


# ----------------- Classes -----------------

def is_user_teacher(user_id: str) -> bool:
    """檢查使用者是否為教師角色。"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        return bool(row and (row.get("role") == "teacher"))


def create_class_for_teacher(teacher_user_id: str, name: str, code: Optional[str] = None) -> Dict[str, Any]:
    """由教師建立班級。

    Args:
        teacher_user_id: 教師之使用者 UUID（classes.teacher_id 參照 teachers.user_id）
        name: 班級名稱
        code: 可選，加入碼（若資料表允許為 NULL）

    Returns:
        新建立的班級資訊
    """
    if not name or not name.strip():
        raise RuntimeError("班級名稱不得為空")

    # 角色檢查
    if not is_user_teacher(teacher_user_id):
        raise PermissionError("只有教師可以建立班級")

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO classes (teacher_id, name, code)
            VALUES (%s, %s, %s)
            RETURNING id, teacher_id, name, code, created_at
            """,
            (teacher_user_id, name.strip(), code),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "id": str(row["id"]),
            "teacher_id": str(row["teacher_id"]),
            "name": row["name"],
            "code": row.get("code"),
            "created_at": iso(row.get("created_at")),
        }


def list_classes_by_teacher(teacher_user_id: str) -> List[Dict[str, Any]]:
    """列出教師名下的所有班級（新到舊）。"""
    if not is_user_teacher(teacher_user_id):
        raise PermissionError("只有教師可以查看自己的班級列表")

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.teacher_id, c.name, c.code, c.created_at,
                   COUNT(cs.student_id) AS student_count,
                   COALESCE(
                     json_agg(
                       json_build_object(
                         'id', u.id,
                         'name', u.full_name,
                         'email', u.email
                       )
                     ) FILTER (WHERE u.id IS NOT NULL),
                     '[]'
                   ) AS students
            FROM classes c
            LEFT JOIN class_students cs ON cs.class_id = c.id
            LEFT JOIN users u ON u.id = cs.student_id
            WHERE c.teacher_id = %s
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """,
            (teacher_user_id,),
        )
        rows = cur.fetchall() or []
        return [
            {
                "id": str(r["id"]),
                "teacher_id": str(r["teacher_id"]),
                "name": r["name"],
                "code": r.get("code"),
                "created_at": iso(r.get("created_at")),
                "student_count": int(r.get("student_count") or 0),
                "students": r.get("students") or [],
            }
            for r in rows
        ]


def list_classes_for_student(student_user_id: str) -> List[Dict[str, Any]]:
    """列出學生所屬的所有班級（新到舊）。"""
    with _get_conn() as conn, conn.cursor() as cur:
        # 確認該 user 是學生（存在 students 表即可）
        if not _is_student_exists(cur, student_user_id):
            raise PermissionError("僅學生可查詢所屬班級")

        cur.execute(
            """
            SELECT c.id, c.teacher_id, c.name, c.code, c.created_at,
                   (SELECT COUNT(*) FROM class_students s WHERE s.class_id = c.id) AS student_count
            FROM class_students cs
            JOIN classes c ON c.id = cs.class_id
            WHERE cs.student_id = %s
            ORDER BY cs.enrolled_at DESC
            """,
            (student_user_id,),
        )
        rows = cur.fetchall() or []
        return [
            {
                "id": str(r["id"]),
                "teacher_id": str(r["teacher_id"]),
                "name": r["name"],
                "code": r.get("code"),
                "created_at": iso(r.get("created_at")),
                "student_count": int(r.get("student_count") or 0),
            }
            for r in rows
        ]


def _get_user_by_email(cur, email: str) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT id, email, full_name, role FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    return dict(row) if row else None


def _is_student_exists(cur, user_id: str) -> bool:
    cur.execute("SELECT 1 FROM students WHERE user_id=%s", (user_id,))
    return bool(cur.fetchone())


def _is_class_owned_by_teacher(cur, class_id: str, teacher_user_id: str) -> bool:
    cur.execute("SELECT 1 FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_user_id))
    return bool(cur.fetchone())


def invite_student_to_class(teacher_user_id: str, class_id: str, student_email: str) -> Dict[str, Any]:
    """由教師將學生加入指定班級（透過學生 email）。"""
    if not is_user_teacher(teacher_user_id):
        raise PermissionError("只有教師可以邀請學生加入班級")
    if not student_email or not student_email.strip():
        raise RuntimeError("學生 email 不得為空")

    with _get_conn() as conn, conn.cursor() as cur:
        # 確認班級歸屬
        if not _is_class_owned_by_teacher(cur, class_id, teacher_user_id):
            raise PermissionError("無權操作此班級或班級不存在")

        # 查找學生
        student = _get_user_by_email(cur, student_email.strip())
        if not student:
            raise RuntimeError("學生不存在，請先註冊該學生帳號")
        if student.get("role") != "student":
            raise RuntimeError("該使用者不是學生角色")
        student_id = student.get("id")
        if not _is_student_exists(cur, student_id):
            raise RuntimeError("學生資料不完整（students 表無記錄）")

        # 寫入關聯（忽略重複）
        cur.execute(
            """
            INSERT INTO class_students (class_id, student_id)
            VALUES (%s, %s)
            ON CONFLICT (class_id, student_id) DO NOTHING
            RETURNING class_id, student_id, enrolled_at
            """,
            (class_id, student_id),
        )
        row = cur.fetchone()
        conn.commit()

        # 如果已存在，沒有 RETURNING；再查詢一次時間
        if not row:
            cur.execute(
                "SELECT class_id, student_id, enrolled_at FROM class_students WHERE class_id=%s AND student_id=%s",
                (class_id, student_id),
            )
            row = cur.fetchone()

        return {
            "class_id": str(row["class_id"]),
            "student_id": str(row["student_id"]),
            "enrolled_at": iso(row.get("enrolled_at")),
            "student": {
                "id": str(student_id),
                "email": student.get("email"),
                "full_name": student.get("full_name"),
            },
        }

def submit_quiz_result(quiz_id: str, student_id: str, answers: List[dict], score: int, total_questions: int) -> dict:
    with _get_conn() as conn, conn.cursor() as cur:
        # Check if quiz exists
        cur.execute("SELECT id FROM quizzes WHERE id = %s", (quiz_id,))
        if not cur.fetchone():
            raise RuntimeError("Quiz not found")

        # Determine next attempt number for this student on this quiz
        cur.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) AS max_attempt FROM quiz_submissions WHERE quiz_id=%s AND student_id=%s",
            (quiz_id, student_id),
        )
        attempt_no = int(cur.fetchone().get("max_attempt") or 0) + 1

        sql = """
        INSERT INTO quiz_submissions (quiz_id, student_id, score, total_questions, answers_json, attempt_no)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, submitted_at, attempt_no
        """
        cur.execute(sql, (quiz_id, student_id, score, total_questions, json_lib.dumps(answers), attempt_no))
        row = cur.fetchone()
        conn.commit()
        return {
            "submission_id": str(row["id"]),
            "submitted_at": iso(row["submitted_at"]),
            "attempt_no": row.get("attempt_no"),
        }

def get_quiz_submissions(quiz_id: str) -> List[dict]:
    sql = """
    SELECT qs.id, qs.student_id, qs.score, qs.total_questions, qs.submitted_at, 
           qs.answers_json,
           qs.attempt_no,
           u.full_name, u.email
    FROM quiz_submissions qs
    JOIN users u ON u.id = qs.student_id
    WHERE qs.quiz_id = %s
    ORDER BY qs.submitted_at DESC, qs.id DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (quiz_id,))
        rows = cur.fetchall()
        
        results = []
        for r in rows:
            answers = r["answers_json"]
            if answers is None:
                answers = []
            elif isinstance(answers, str):
                try:
                    answers = json_lib.loads(answers)
                except:
                    answers = []
            
            results.append({
                "submission_id": str(r["id"]),
                "student_id": str(r["student_id"]),
                "student_name": r["full_name"],
                "student_email": r["email"],
                "score": r["score"],
                "total_questions": r["total_questions"],
                "submitted_at": iso(r["submitted_at"]),
                "answers": answers,
                "attempt_no": r.get("attempt_no"),
            })
        return results

def get_student_quiz_submission(quiz_id: str, student_id: str) -> Optional[dict]:
    sql = """
    SELECT id, score, total_questions, answers_json, submitted_at
    FROM quiz_submissions
    WHERE quiz_id = %s AND student_id = %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (quiz_id, student_id))
        row = cur.fetchone()
        if not row:
            return None
        
        answers = row["answers_json"]
        if isinstance(answers, str):
            answers = json_lib.loads(answers)
            
        return {
            "submission_id": str(row["id"]),
            "score": row["score"],
            "total_questions": row["total_questions"],
            "answers": answers,
            "submitted_at": iso(row["submitted_at"])
        }


# ----------------- Exams -----------------

def _default_exam_title(cur, file_ids: List[str]) -> str:
    """生成預設考試標題"""
    cur.execute("SELECT name FROM documents WHERE id = ANY(%s::uuid[]) LIMIT 3", (file_ids,))
    names = [row["name"] for row in cur.fetchall()]
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - 考試"
    elif len(names) > 1:
        prefix = f"{len(names)} 個文件的考試"
    else:
        prefix = "考試"
    now = datetime.now()
    return f"{prefix} ({now.strftime('%m/%d %H:%M')})"


def save_exam(
    exam_id: str,
    exam_name: str,
    questions: List[Dict[str, Any]],
    file_ids: List[str],
    class_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    difficulty: str = "medium",
    duration_minutes: Optional[int] = None,
    pdf_path: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    保存考試到資料庫
    
    Args:
        exam_id: 考試 ID（由 graph.py 生成）
        exam_name: 考試名稱/標題
        questions: 題目列表（ExamQuestion 的 dict 格式）
        file_ids: 來源文件 ID 列表
        class_id: 所屬班級 ID
        owner_id: 創建考試的老師 ID
        difficulty: 難度級別
        duration_minutes: 考試時間限制（分鐘）
        pdf_path: PDF 檔案路徑
        description: 考試描述
    
    Returns:
        保存結果
    """
    # 計算總分
    total_marks = sum(q.get("marks", 1) for q in questions)
    
    with _get_conn() as conn, conn.cursor() as cur:
        # 如果沒有提供名稱，生成預設名稱
        title = exam_name or _default_exam_title(cur, file_ids)
        
        # 插入考試主表
        cur.execute("""
            INSERT INTO exams (id, title, description, questions_json, difficulty, total_marks, 
                              duration_minutes, class_id, owner_id, pdf_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                questions_json = EXCLUDED.questions_json,
                difficulty = EXCLUDED.difficulty,
                total_marks = EXCLUDED.total_marks,
                duration_minutes = EXCLUDED.duration_minutes,
                pdf_path = EXCLUDED.pdf_path,
                updated_at = now()
            RETURNING id, created_at
        """, (
            exam_id,
            title,
            description,
            json_lib.dumps(questions),
            difficulty,
            total_marks,
            duration_minutes,
            class_id,
            owner_id,
            pdf_path,
        ))
        row = cur.fetchone()
        
        # 刪除舊的題目並插入新題目到 exam_questions 表
        cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
        for idx, q in enumerate(questions):
            cur.execute("""
                INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                VALUES (%s, %s, %s, %s)
            """, (
                exam_id,
                idx,
                json_lib.dumps(q),
                q.get("marks", 1),
            ))
        
        # 關聯到來源文件
        if file_ids:
            cur.execute("DELETE FROM exam_documents WHERE exam_id = %s", (exam_id,))
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO exam_documents (exam_id, document_id) VALUES %s ON CONFLICT DO NOTHING",
                [(exam_id, fid) for fid in file_ids],
            )
        
        conn.commit()
        
        return {
            "exam_id": str(row["id"]),
            "title": title,
            "created_at": iso(row["created_at"]),
            "num_questions": len(questions),
            "total_marks": total_marks,
        }


def get_exams_by_class(class_id: str) -> List[Dict[str, Any]]:
    """
    獲取指定班級的考試列表
    """
    sql = """
    SELECT e.id, e.title, e.description, e.difficulty, e.total_marks, e.duration_minutes,
           e.created_at, e.updated_at, e.is_published, e.pdf_path, e.owner_id,
           e.start_at, e.end_at,
           (SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS num_questions,
           ARRAY_AGG(DISTINCT ed.document_id)::uuid[] AS file_ids
    FROM exams e
    LEFT JOIN exam_documents ed ON ed.exam_id = e.id
    WHERE e.class_id = %s
    GROUP BY e.id
    ORDER BY e.created_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (class_id,))
        rows = cur.fetchall() or []
        
        # 獲取關聯的文件名稱
        exam_ids = [r["id"] for r in rows]
        docs = {}
        if exam_ids:
            cur.execute("""
                SELECT ed.exam_id, d.id, d.name
                FROM exam_documents ed
                JOIN documents d ON d.id = ed.document_id
                WHERE ed.exam_id = ANY(%s::uuid[])
            """, (exam_ids,))
            for r in cur.fetchall():
                eid = str(r["exam_id"])
                docs.setdefault(eid, []).append({"id": str(r["id"]), "name": r["name"]})
        
        return [
            {
                "id": str(r["id"]),
                "title": r["title"] or "未命名考試",
                "description": r["description"],
                "difficulty": r["difficulty"],
                "total_marks": r["total_marks"],
                "duration_minutes": r["duration_minutes"],
                "num_questions": r["num_questions"] or 0,
                "created_at": iso(r["created_at"]),
                "updated_at": iso(r["updated_at"]),
                "is_published": r["is_published"],
                "start_at": iso(r["start_at"]),
                "end_at": iso(r["end_at"]),
                "pdf_path": r["pdf_path"],
                "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
                "file_ids": [str(x) for x in (r["file_ids"] or []) if x],
                "documents": docs.get(str(r["id"]), []),
            }
            for r in rows
        ]


def get_exam_by_id(exam_id: str, user_id: Optional[str] = None, include_answers: bool = True) -> Dict[str, Any]:
    """
    根據 ID 獲取考試詳情
    
    Args:
        exam_id: 考試 ID
        user_id: 用戶 ID（用於權限檢查）
        include_answers: 是否包含答案（學生作答時應設為 False）
    """
    sql = """
    SELECT id, title, description, questions_json, difficulty, total_marks, duration_minutes,
           class_id, owner_id, created_at, updated_at, is_published, pdf_path, start_at, end_at
    FROM exams WHERE id = %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id,))
        r = cur.fetchone()
        if not r:
            raise RuntimeError("考試不存在")
        
        # 獲取關聯文件
        cur.execute("""
            SELECT d.id, d.name, d.class_id
            FROM exam_documents ed
            JOIN documents d ON d.id = ed.document_id
            WHERE ed.exam_id = %s
        """, (exam_id,))
        docs_rows = cur.fetchall()
        documents = [{"id": str(d["id"]), "name": d["name"]} for d in docs_rows]
        
        # 獲取題目從 exam_questions 表
        cur.execute("""
            SELECT id, position, question_snapshot, max_marks
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY position ASC
        """, (exam_id,))
        eq_rows = cur.fetchall()
        
        # 權限檢查
        if user_id:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row else None
            
            if role == 'student':
                # 學生只能訪問已發布的考試
                if not r["is_published"]:
                    raise PermissionError("此考試尚未發布")
                # 檢查學生是否在班級中
                if r["class_id"]:
                    cur.execute(
                        "SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s",
                        (r["class_id"], user_id)
                    )
                    if not cur.fetchone():
                        raise PermissionError("您不在此班級中")
        
        # 處理題目 - 優先使用 exam_questions 表，否則使用 questions_json
        if eq_rows:
            questions = []
            for eq in eq_rows:
                q_snapshot = eq["question_snapshot"]
                if isinstance(q_snapshot, str):
                    q_snapshot = json_lib.loads(q_snapshot)
                q_snapshot["exam_question_id"] = str(eq["id"])  # 添加題目 ID
                questions.append(q_snapshot)
        else:
            questions = r["questions_json"] or []
            if isinstance(questions, str):
                questions = json_lib.loads(questions)
        
        # 如果不包含答案（學生作答時），移除答案相關欄位
        if not include_answers:
            for q in questions:
                q.pop("correct_answer_index", None)
                q.pop("model_answer", None)
                q.pop("marking_scheme", None)
                q.pop("rationale", None)
        
        return {
            "id": str(r["id"]),
            "title": r["title"] or "未命名考試",
            "description": r["description"],
            "questions": questions,
            "difficulty": r["difficulty"],
            "total_marks": r["total_marks"],
            "duration_minutes": r["duration_minutes"],
            "num_questions": len(questions),
            "class_id": str(r["class_id"]) if r["class_id"] else None,
            "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
            "created_at": iso(r["created_at"]),
            "updated_at": iso(r["updated_at"]),
            "is_published": r["is_published"],
            "start_at": iso(r["start_at"]),
            "end_at": iso(r["end_at"]),
            "pdf_path": r["pdf_path"],
            "file_ids": [d["id"] for d in documents],
            "documents": documents,
        }


def update_exam(
    exam_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    questions: Optional[List[Dict[str, Any]]] = None,
    difficulty: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    file_ids: Optional[List[str]] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    更新考試
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # 獲取現有考試
        cur.execute("SELECT id, questions_json FROM exams WHERE id = %s", (exam_id,))
        existing = cur.fetchone()
        if not existing:
            raise RuntimeError("考試不存在")
        
        # 準備更新的欄位
        updates = ["updated_at = now()"]
        params = []
        
        if title is not None:
            updates.append("title = %s")
            params.append(title)
        
        if description is not None:
            updates.append("description = %s")
            params.append(description)
        
        if questions is not None:
            updates.append("questions_json = %s")
            params.append(json_lib.dumps(questions))
            total_marks = sum(q.get("marks", 1) for q in questions)
            updates.append("total_marks = %s")
            params.append(total_marks)
        
        if difficulty is not None:
            updates.append("difficulty = %s")
            params.append(difficulty)
        
        if duration_minutes is not None:
            updates.append("duration_minutes = %s")
            params.append(duration_minutes if duration_minutes > 0 else None)
        
        if start_at is not None:
            updates.append("start_at = %s")
            params.append(start_at if start_at else None)
        
        if end_at is not None:
            updates.append("end_at = %s")
            params.append(end_at if end_at else None)
        
        params.append(exam_id)
        cur.execute(
            f"UPDATE exams SET {', '.join(updates)} WHERE id = %s RETURNING id, title, total_marks",
            params
        )
        row = cur.fetchone()
        
        # 如果更新了題目，也要更新 exam_questions 表
        if questions is not None:
            cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
            for idx, q in enumerate(questions):
                cur.execute("""
                    INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                    VALUES (%s, %s, %s, %s)
                """, (
                    exam_id,
                    idx,
                    json_lib.dumps(q),
                    q.get("marks", 1),
                ))
        
        # 更新文件關聯
        if file_ids is not None:
            cur.execute("DELETE FROM exam_documents WHERE exam_id = %s", (exam_id,))
            if file_ids:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO exam_documents (exam_id, document_id) VALUES %s ON CONFLICT DO NOTHING",
                    [(exam_id, fid) for fid in file_ids],
                )
        
        conn.commit()
        
        return {
            "exam_id": str(row["id"]),
            "title": row["title"],
            "total_marks": row["total_marks"],
        }


def delete_exam(exam_id: str) -> Dict[str, Any]:
    """刪除考試"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM exams WHERE id = %s RETURNING id, title", (exam_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("考試不存在")
        conn.commit()
        return {"message": "考試已成功刪除", "exam_id": str(row["id"]), "title": row["title"]}


def publish_exam(exam_id: str, is_published: bool = True) -> Dict[str, Any]:
    """發布或取消發布考試"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE exams SET is_published = %s, updated_at = now() WHERE id = %s RETURNING id, title, is_published",
            (is_published, exam_id)
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("考試不存在")
        conn.commit()
        return {
            "exam_id": str(row["id"]),
            "title": row["title"],
            "is_published": row["is_published"],
        }


def start_exam_submission(exam_id: str, student_id: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
    """
    學生開始作答考試
    建立一筆 in_progress 狀態的提交記錄
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # 檢查考試是否存在且已發布
        cur.execute("SELECT id, is_published, duration_minutes, start_at, end_at FROM exams WHERE id = %s", (exam_id,))
        exam = cur.fetchone()
        if not exam:
            raise RuntimeError("考試不存在")
        if not exam["is_published"]:
            raise RuntimeError("考試尚未發布")
        
        # 計算下一個嘗試次數
        cur.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) AS max_attempt FROM exam_submissions WHERE exam_id = %s AND student_id = %s",
            (exam_id, student_id)
        )
        attempt_no = int(cur.fetchone()["max_attempt"] or 0) + 1
        
        # 建立提交記錄
        cur.execute("""
            INSERT INTO exam_submissions (exam_id, student_id, attempt_no, status, meta)
            VALUES (%s, %s, %s, 'in_progress', %s)
            RETURNING id, started_at, attempt_no
        """, (exam_id, student_id, attempt_no, json_lib.dumps(meta or {})))
        row = cur.fetchone()
        conn.commit()
        
        return {
            "submission_id": str(row["id"]),
            "started_at": iso(row["started_at"]),
            "attempt_no": row["attempt_no"],
            "duration_minutes": exam["duration_minutes"],
        }


def submit_exam(
    submission_id: str,
    answers: List[Dict[str, Any]],
    time_spent_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    學生提交考試答案
    
    Args:
        submission_id: 提交記錄 ID
        answers: 學生答案列表，每個答案應包含 exam_question_id 或 question_id
        time_spent_seconds: 花費時間（秒）
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # 獲取提交記錄和考試資訊
        cur.execute("""
            SELECT es.id, es.exam_id, es.status, e.questions_json, e.total_marks
            FROM exam_submissions es
            JOIN exams e ON e.id = es.exam_id
            WHERE es.id = %s
        """, (submission_id,))
        sub = cur.fetchone()
        if not sub:
            raise RuntimeError("提交記錄不存在")
        if sub["status"] != "in_progress":
            raise RuntimeError("此提交已完成，無法再次提交")
        
        exam_id = sub["exam_id"]
        
        # 獲取 exam_questions 表中的題目
        cur.execute("""
            SELECT id, position, question_snapshot, max_marks
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY position ASC
        """, (exam_id,))
        eq_rows = cur.fetchall()
        
        # 建立題目查找字典（支援 exam_question_id 和 question_id 兩種方式）
        eq_map_by_id = {str(eq["id"]): eq for eq in eq_rows}
        eq_map_by_q_id = {}
        for eq in eq_rows:
            snapshot = eq["question_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json_lib.loads(snapshot)
            q_id = snapshot.get("question_id")
            if q_id:
                eq_map_by_q_id[q_id] = eq
        
        # 計算分數（選擇題自動批改）並保存到 exam_answers 表
        score = 0
        graded_answers = []
        
        for ans in answers:
            # 查找對應的 exam_question
            eq_id = ans.get("exam_question_id")
            q_id = ans.get("question_id")
            
            eq = None
            if eq_id:
                eq = eq_map_by_id.get(eq_id)
            elif q_id:
                eq = eq_map_by_q_id.get(q_id)
            
            if not eq:
                graded_answers.append(ans)
                continue
            
            snapshot = eq["question_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json_lib.loads(snapshot)
            
            is_correct = False
            marks_earned = 0
            
            # 自動批改選擇題
            if snapshot.get("question_type") == "multiple_choice":
                correct_idx = snapshot.get("correct_answer_index")
                user_idx = ans.get("answer_index")
                # 也支援 selected_options 格式
                if user_idx is None and ans.get("selected_options"):
                    selected = ans.get("selected_options")
                    if isinstance(selected, list) and len(selected) > 0:
                        user_idx = selected[0]
                
                is_correct = (correct_idx is not None and user_idx == correct_idx)
                marks_earned = eq["max_marks"] if is_correct else 0
            
            graded_answer = {
                **ans,
                "exam_question_id": str(eq["id"]),
                "is_correct": is_correct,
                "marks_earned": marks_earned,
            }
            graded_answers.append(graded_answer)
            score += marks_earned
            
            # 插入到 exam_answers 表
            selected_options = ans.get("selected_options")
            if selected_options is None and ans.get("answer_index") is not None:
                selected_options = [ans.get("answer_index")]
            
            cur.execute("""
                INSERT INTO exam_answers (
                    submission_id, exam_question_id, question_snapshot,
                    answer_text, selected_options, time_spent_seconds,
                    is_correct, marks_earned
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                submission_id,
                eq["id"],
                json_lib.dumps(snapshot),
                ans.get("answer_text"),
                json_lib.dumps(selected_options) if selected_options else None,
                ans.get("time_spent_seconds"),
                is_correct,
                marks_earned,
            ))
        
        # 更新提交記錄
        cur.execute("""
            UPDATE exam_submissions
            SET score = %s,
                total_marks = %s,
                time_spent_seconds = %s,
                status = 'submitted',
                submitted_at = now()
            WHERE id = %s
            RETURNING id, submitted_at, score, total_marks
        """, (
            score,
            sub["total_marks"],
            time_spent_seconds,
            submission_id,
        ))
        row = cur.fetchone()
        conn.commit()
        
        return {
            "submission_id": str(row["id"]),
            "submitted_at": iso(row["submitted_at"]),
            "score": row["score"],
            "total_marks": row["total_marks"],
            "status": "submitted",
        }


def get_exam_submissions(exam_id: str) -> List[Dict[str, Any]]:
    """
    獲取考試的所有提交記錄（老師用）
    """
    sql = """
    SELECT es.id, es.student_id, es.attempt_no, es.score, es.total_marks,
           es.time_spent_seconds, es.status, es.started_at, es.submitted_at,
           es.teacher_comment, es.graded_by, es.graded_at, es.meta,
           u.full_name AS student_name, u.email AS student_email
    FROM exam_submissions es
    JOIN users u ON u.id = es.student_id
    WHERE es.exam_id = %s
    ORDER BY es.submitted_at DESC NULLS LAST, es.started_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id,))
        rows = cur.fetchall() or []
        
        # 獲取所有提交的答案
        submission_ids = [r["id"] for r in rows]
        answers_map = {}
        if submission_ids:
            cur.execute("""
                SELECT ea.submission_id, ea.id, ea.exam_question_id, ea.question_snapshot,
                       ea.answer_text, ea.selected_options, ea.time_spent_seconds,
                       ea.is_correct, ea.marks_earned, ea.teacher_feedback, ea.attachments
                FROM exam_answers ea
                JOIN exam_questions eq ON ea.exam_question_id = eq.id
                WHERE ea.submission_id = ANY(%s::uuid[])
                ORDER BY eq.position ASC
            """, (submission_ids,))
            for a in cur.fetchall():
                sid = str(a["submission_id"])
                ans_data = {
                    "id": str(a["id"]),
                    "exam_question_id": str(a["exam_question_id"]),
                    "question_snapshot": a["question_snapshot"] if isinstance(a["question_snapshot"], dict) else json_lib.loads(a["question_snapshot"]) if a["question_snapshot"] else None,
                    "answer_text": a["answer_text"],
                    "selected_options": a["selected_options"] if isinstance(a["selected_options"], list) else json_lib.loads(a["selected_options"]) if a["selected_options"] else None,
                    "time_spent_seconds": a["time_spent_seconds"],
                    "is_correct": a["is_correct"],
                    "marks_earned": a["marks_earned"],
                    "teacher_feedback": a["teacher_feedback"],
                    "attachments": a["attachments"] if isinstance(a["attachments"], list) else json_lib.loads(a["attachments"]) if a["attachments"] else [],
                }
                answers_map.setdefault(sid, []).append(ans_data)
        
        results = []
        for r in rows:
            sid = str(r["id"])
            meta = r["meta"]
            if meta and isinstance(meta, str):
                meta = json_lib.loads(meta)
            
            results.append({
                "submission_id": sid,
                "student_id": str(r["student_id"]),
                "student_name": r["student_name"],
                "student_email": r["student_email"],
                "attempt_no": r["attempt_no"],
                "score": r["score"],
                "total_marks": r["total_marks"],
                "time_spent_seconds": r["time_spent_seconds"],
                "status": r["status"],
                "started_at": iso(r["started_at"]),
                "submitted_at": iso(r["submitted_at"]),
                "teacher_comment": r["teacher_comment"],
                "graded_by": str(r["graded_by"]) if r["graded_by"] else None,
                "graded_at": iso(r["graded_at"]),
                "meta": meta or {},
                "answers": answers_map.get(sid, []),
            })
        
        return results


def get_student_exam_submissions(exam_id: str, student_id: str) -> List[Dict[str, Any]]:
    """
    獲取學生在特定考試的所有提交記錄
    """
    sql = """
    SELECT id, attempt_no, score, total_marks, time_spent_seconds, status,
           started_at, submitted_at, teacher_comment, graded_at, meta
    FROM exam_submissions
    WHERE exam_id = %s AND student_id = %s
    ORDER BY attempt_no DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id, student_id))
        rows = cur.fetchall() or []
        
        # 獲取所有提交的答案
        submission_ids = [r["id"] for r in rows]
        answers_map = {}
        if submission_ids:
            cur.execute("""
                SELECT ea.submission_id, ea.id, ea.exam_question_id, ea.question_snapshot,
                       ea.answer_text, ea.selected_options, ea.time_spent_seconds,
                       ea.is_correct, ea.marks_earned, ea.teacher_feedback
                FROM exam_answers ea
                JOIN exam_questions eq ON ea.exam_question_id = eq.id
                WHERE ea.submission_id = ANY(%s::uuid[])
                ORDER BY eq.position ASC
            """, (submission_ids,))
            for a in cur.fetchall():
                sid = str(a["submission_id"])
                ans_data = {
                    "id": str(a["id"]),
                    "exam_question_id": str(a["exam_question_id"]),
                    "question_snapshot": a["question_snapshot"] if isinstance(a["question_snapshot"], dict) else json_lib.loads(a["question_snapshot"]) if a["question_snapshot"] else None,
                    "answer_text": a["answer_text"],
                    "selected_options": a["selected_options"] if isinstance(a["selected_options"], list) else json_lib.loads(a["selected_options"]) if a["selected_options"] else None,
                    "time_spent_seconds": a["time_spent_seconds"],
                    "is_correct": a["is_correct"],
                    "marks_earned": a["marks_earned"],
                    "teacher_feedback": a["teacher_feedback"],
                }
                answers_map.setdefault(sid, []).append(ans_data)
        
        results = []
        for r in rows:
            sid = str(r["id"])
            meta = r["meta"]
            if meta and isinstance(meta, str):
                meta = json_lib.loads(meta)
            
            results.append({
                "submission_id": sid,
                "attempt_no": r["attempt_no"],
                "score": r["score"],
                "total_marks": r["total_marks"],
                "time_spent_seconds": r["time_spent_seconds"],
                "status": r["status"],
                "started_at": iso(r["started_at"]),
                "submitted_at": iso(r["submitted_at"]),
                "teacher_comment": r["teacher_comment"],
                "graded_at": iso(r["graded_at"]),
                "meta": meta or {},
                "answers": answers_map.get(sid, []),
            })
        
        return results


def grade_exam_submission(
    submission_id: str,
    teacher_id: str,
    answers_grades: Optional[List[Dict[str, Any]]] = None,
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    老師批改考試
    
    Args:
        submission_id: 提交記錄 ID
        teacher_id: 批改老師 ID
        answers_grades: 每題的批改結果 [{"exam_question_id": "...", "marks_earned": 2, "teacher_feedback": "..."}]
        teacher_comment: 整體評語
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # 獲取現有提交
        cur.execute(
            "SELECT id, total_marks FROM exam_submissions WHERE id = %s",
            (submission_id,)
        )
        sub = cur.fetchone()
        if not sub:
            raise RuntimeError("提交記錄不存在")
        
        # 更新 exam_answers 表中的批改結果
        if answers_grades:
            for g in answers_grades:
                # 支援 exam_question_id 或 answer_id
                answer_id = g.get("answer_id")
                eq_id = g.get("exam_question_id")
                
                if answer_id:
                    cur.execute("""
                        UPDATE exam_answers
                        SET marks_earned = %s,
                            teacher_feedback = %s
                        WHERE id = %s
                    """, (
                        g.get("marks_earned", 0),
                        g.get("teacher_feedback"),
                        answer_id,
                    ))
                elif eq_id:
                    cur.execute("""
                        UPDATE exam_answers
                        SET marks_earned = %s,
                            teacher_feedback = %s
                        WHERE submission_id = %s AND exam_question_id = %s
                    """, (
                        g.get("marks_earned", 0),
                        g.get("teacher_feedback"),
                        submission_id,
                        eq_id,
                    ))
        
        # 計算總分（從 exam_answers 表）
        cur.execute("""
            SELECT COALESCE(SUM(marks_earned), 0) AS total_score
            FROM exam_answers
            WHERE submission_id = %s
        """, (submission_id,))
        score = cur.fetchone()["total_score"]
        
        # 更新提交記錄
        cur.execute("""
            UPDATE exam_submissions
            SET score = %s,
                teacher_comment = COALESCE(%s, teacher_comment),
                graded_by = %s,
                graded_at = now(),
                grading_source = 'teacher',
                status = 'graded'
            WHERE id = %s
            RETURNING id, score, graded_at
        """, (
            score,
            teacher_comment,
            teacher_id,
            submission_id,
        ))
        row = cur.fetchone()
        conn.commit()
        
        return {
            "submission_id": str(row["id"]),
            "score": row["score"],
            "total_marks": sub["total_marks"],
            "graded_at": iso(row["graded_at"]),
            "status": "graded",
        }


def get_submission_with_answers(submission_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single submission with all its answers.
    Used for AI grading.
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # Get submission
        cur.execute("""
            SELECT id, exam_id, student_id, score, total_marks, status,
                   started_at, submitted_at, teacher_comment, graded_at, graded_by,
                   grading_source, meta
            FROM exam_submissions
            WHERE id = %s
        """, (submission_id,))
        sub = cur.fetchone()
        
        if not sub:
            return None
        
        # Get answers
        cur.execute("""
            SELECT a.id, a.exam_question_id, a.question_snapshot, a.answer_text,
                   a.selected_options, a.time_spent_seconds, a.is_correct,
                   a.marks_earned, a.teacher_feedback
            FROM exam_answers a
            JOIN exam_questions q ON a.exam_question_id = q.id
            WHERE a.submission_id = %s
            ORDER BY q.position ASC
        """, (submission_id,))
        answers_rows = cur.fetchall() or []
        
        answers = []
        for a in answers_rows:
            snapshot = a["question_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json_lib.loads(snapshot)
            
            answers.append({
                "id": str(a["id"]),
                "exam_question_id": str(a["exam_question_id"]),
                "question_snapshot": snapshot,
                "answer_text": a["answer_text"],
                "selected_options": a["selected_options"] if isinstance(a["selected_options"], list) else json_lib.loads(a["selected_options"]) if a["selected_options"] else None,
                "time_spent_seconds": a["time_spent_seconds"],
                "is_correct": a["is_correct"],
                "marks_earned": a["marks_earned"],
                "teacher_feedback": a["teacher_feedback"],
            })
        
        return {
            "submission_id": str(sub["id"]),
            "exam_id": str(sub["exam_id"]),
            "student_id": str(sub["student_id"]),
            "score": sub["score"],
            "total_marks": sub["total_marks"],
            "status": sub["status"],
            "started_at": iso(sub["started_at"]),
            "submitted_at": iso(sub["submitted_at"]),
            "teacher_comment": sub["teacher_comment"],
            "graded_at": iso(sub["graded_at"]),
            "graded_by": str(sub["graded_by"]) if sub["graded_by"] else None,
            "grading_source": sub["grading_source"],
            "answers": answers,
        }


def ai_grade_exam_submission(
    submission_id: str,
    graded_answers: List[Dict[str, Any]],
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save AI grading results to database.
    Sets status to 'ai_graded' and grading_source to 'ai'.
    Teacher can later override with manual grading.
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # Verify submission exists
        cur.execute("""
            SELECT id, total_marks FROM exam_submissions WHERE id = %s
        """, (submission_id,))
        sub = cur.fetchone()
        if not sub:
            raise RuntimeError(f"Submission {submission_id} not found")
        
        # Update each answer
        for g in graded_answers:
            answer_id = g.get("answer_id")
            eq_id = g.get("exam_question_id")
            
            if answer_id:
                cur.execute("""
                    UPDATE exam_answers
                    SET marks_earned = %s,
                        teacher_feedback = %s,
                        is_correct = %s
                    WHERE id = %s
                """, (
                    g.get("marks_earned", 0),
                    g.get("teacher_feedback"),
                    g.get("is_correct", False),
                    answer_id,
                ))
            elif eq_id:
                cur.execute("""
                    UPDATE exam_answers
                    SET marks_earned = %s,
                        teacher_feedback = %s,
                        is_correct = %s
                    WHERE submission_id = %s AND exam_question_id = %s
                """, (
                    g.get("marks_earned", 0),
                    g.get("teacher_feedback"),
                    g.get("is_correct", False),
                    submission_id,
                    eq_id,
                ))
        
        # Calculate total score
        cur.execute("""
            SELECT COALESCE(SUM(marks_earned), 0) AS total_score
            FROM exam_answers
            WHERE submission_id = %s
        """, (submission_id,))
        score = cur.fetchone()["total_score"]
        
        # Update submission with AI grading status
        if teacher_comment:
            cur.execute("""
                UPDATE exam_submissions
                SET score = %s,
                    graded_at = now(),
                    graded_by = NULL,
                    grading_source = 'ai',
                    status = 'ai_graded',
                    teacher_comment = %s
                WHERE id = %s
                RETURNING id, score, graded_at, status, teacher_comment
            """, (score, teacher_comment, submission_id))
        else:
            cur.execute("""
                UPDATE exam_submissions
                SET score = %s,
                    graded_at = now(),
                    graded_by = NULL,
                    grading_source = 'ai',
                    status = 'ai_graded'
                WHERE id = %s
                RETURNING id, score, graded_at, status, teacher_comment
            """, (score, submission_id))
            
        row = cur.fetchone()
        conn.commit()
        
        return {
            "submission_id": str(row["id"]),
            "score": row["score"],
            "total_marks": sub["total_marks"],
            "graded_at": iso(row["graded_at"]),
            "status": row["status"],
            "grading_source": "ai",
            "teacher_comment": row.get("teacher_comment")
        }
