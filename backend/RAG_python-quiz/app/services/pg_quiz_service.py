# -*- coding: utf-8 -*-
from datetime import datetime
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.pg_db import _get_conn
from app.services.pg_shared import (
    fetch_default_document_names,
    fetch_linked_documents,
    filter_linked_documents,
    insert_submission_with_attempt,
    linked_document_ids,
    maybe_iso,
    maybe_json_load,
    map_quiz_submission_row,
    replace_linked_documents,
    stringify_id,
    stringify_id_list,
)


def _default_quiz_name(cur, file_ids: List[str]) -> str:
    names = fetch_default_document_names(cur, file_ids)
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - 測驗"
    elif len(names) > 1:
        prefix = f"{len(names)} 個文件的測驗"
    else:
        prefix = "測驗"
    now = datetime.now()
    return f"{prefix} ({now.strftime('%m/%d %H:%M')})"


def save_quiz(
    quiz_data: Dict[str, Any],
    file_ids: List[str],
    quiz_name: str = None,
    class_id: str = None,
) -> Dict[str, Any]:
    """保存 Quiz 以及對應文件關聯，結構對齊原實作。"""
    with _get_conn() as conn, conn.cursor() as cur:
        name = quiz_name or _default_quiz_name(cur, file_ids)
        cur.execute(
            """
            INSERT INTO quizzes (name, questions_json, source_text_length, was_summarized, num_questions, class_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """,
            (
                name,
                json_lib.dumps(quiz_data["questions"]),
                quiz_data.get("source_text_length"),
                quiz_data.get("was_summarized", False),
                len(quiz_data["questions"]),
                class_id,
            ),
        )
        row = cur.fetchone()
        quiz_id = str(row["id"])
        replace_linked_documents(cur, "quiz_documents", "quiz_id", quiz_id, file_ids)
        conn.commit()
        return {
            "quiz_id": quiz_id,
            "name": name,
            "created_at": int(row["created_at"].timestamp() * 1000)
            if isinstance(row["created_at"], datetime)
            else row["created_at"],
            "num_questions": len(quiz_data["questions"]),
        }


def update_quiz(
    quiz_id: str,
    quiz_data: Dict[str, Any],
    name: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update existing quiz's questions and optionally name and linked documents."""
    if not quiz_data or "questions" not in quiz_data:
        raise RuntimeError("quiz_data must contain 'questions'")

    with _get_conn() as conn, conn.cursor() as cur:
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

        if file_ids is not None:
            replace_linked_documents(cur, "quiz_documents", "quiz_id", quiz_id, file_ids)

        conn.commit()
        return {
            "quiz_id": stringify_id(row["id"]),
            "name": row["name"],
            "num_questions": len(quiz_data["questions"]),
        }


def get_all_quizzes(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
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
            cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row and row.get("role") else None
            if role == "teacher":
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
        quiz_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "quiz_documents", "quiz_id", quiz_ids)

        quizzes = []
        for r in rows:
            qid = stringify_id(r["id"])
            quizzes.append(
                {
                    "id": qid,
                    "name": r["name"] or "未命名測驗",
                    "num_questions": r["num_questions"],
                    "created_at": maybe_iso(r["created_at"]),
                    "file_ids": stringify_id_list(r["file_ids"]),
                    "was_summarized": r["was_summarized"],
                    "source_text_length": r["source_text_length"],
                    "documents": [d for d in (docs.get(qid) or []) if d.get("id")],
                }
            )
        return quizzes


def get_quizzes_by_class(class_id: str) -> List[Dict[str, Any]]:
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

        quiz_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "quiz_documents", "quiz_id", quiz_ids)

        quizzes = []
        for r in rows:
            qid = stringify_id(r["id"])
            quizzes.append(
                {
                    "id": qid,
                    "name": r["name"] or "未命名測驗",
                    "num_questions": r["num_questions"],
                    "created_at": maybe_iso(r["created_at"]),
                    "file_ids": stringify_id_list(r["file_ids"]),
                    "was_summarized": r["was_summarized"],
                    "source_text_length": r["source_text_length"],
                    "documents": [d for d in (docs.get(qid) or []) if d.get("id")],
                }
            )
        return quizzes


def get_quiz_by_id(quiz_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    sql = """
    SELECT id, name, questions_json, num_questions, created_at, was_summarized, source_text_length
    FROM quizzes WHERE id=%s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (quiz_id,))
        r = cur.fetchone()
        if not r:
            raise RuntimeError("測驗不存在")

        documents = fetch_linked_documents(
            cur,
            "quiz_documents",
            "quiz_id",
            [quiz_id],
            include_class_id=True,
        ).get(quiz_id, [])

        if user_id:
            cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row and row.get("role") else None
            allowed = False
            if role == "teacher":
                class_ids = [d["class_id"] for d in documents if d.get("class_id")]
                if class_ids:
                    cur.execute(
                        "SELECT 1 FROM classes WHERE id = ANY(%s::uuid[]) AND teacher_id = %s LIMIT 1",
                        (class_ids, user_id),
                    )
                    if cur.fetchone():
                        allowed = True
            else:
                class_ids = [d["class_id"] for d in documents if d.get("class_id")]
                if class_ids:
                    cur.execute(
                        "SELECT 1 FROM class_students WHERE class_id = ANY(%s::uuid[]) AND student_id = %s LIMIT 1",
                        (class_ids, user_id),
                    )
                    if cur.fetchone():
                        allowed = True

            if not allowed:
                raise PermissionError("無權訪問此測驗")

        questions = maybe_json_load(r["questions_json"], [])
        return {
            "id": stringify_id(r["id"]),
            "name": r["name"] or "未命名測驗",
            "questions": questions,
            "num_questions": r["num_questions"],
            "created_at": maybe_iso(r["created_at"]),
            "file_ids": linked_document_ids(documents),
            "was_summarized": r["was_summarized"],
            "source_text_length": r["source_text_length"],
            "documents": [
                {"id": document["id"], "name": document["name"]}
                for document in filter_linked_documents(documents)
            ],
        }


def delete_quiz(quiz_id: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM quizzes WHERE id=%s RETURNING id", (quiz_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("測驗不存在")
        return {"message": "測驗已成功刪除", "quiz_id": str(quiz_id)}


def submit_quiz_result(
    quiz_id: str, student_id: str, answers: List[dict], score: int, total_questions: int
) -> dict:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM quizzes WHERE id = %s", (quiz_id,))
        if not cur.fetchone():
            raise RuntimeError("Quiz not found")

        sql = """
        INSERT INTO quiz_submissions (quiz_id, student_id, score, total_questions, answers_json, attempt_no)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, submitted_at, attempt_no
        """
        row, _attempt_no = insert_submission_with_attempt(
            cur,
            "quiz_submissions",
            {"quiz_id": quiz_id, "student_id": student_id},
            sql,
            lambda attempt_no: (
                quiz_id,
                student_id,
                score,
                total_questions,
                json_lib.dumps(answers),
                attempt_no,
            ),
        )
        conn.commit()
        return {
            "submission_id": stringify_id(row["id"]),
            "submitted_at": maybe_iso(row["submitted_at"]),
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
        return [
            map_quiz_submission_row(
                {
                    **row,
                    "student_name": row.get("full_name"),
                    "student_email": row.get("email"),
                },
                include_student=True,
            )
            for row in rows
        ]


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

        return map_quiz_submission_row(row)


__all__ = [
    "_default_quiz_name",
    "delete_quiz",
    "get_all_quizzes",
    "get_quiz_by_id",
    "get_quiz_submissions",
    "get_quizzes_by_class",
    "get_student_quiz_submission",
    "save_quiz",
    "submit_quiz_result",
    "update_quiz",
]
