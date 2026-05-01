# -*- coding: utf-8 -*-
from datetime import datetime
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.exceptions import NotFoundError, NotReleasedError, PermissionDeniedError
from app.services.pg_db import _get_conn
from app.services.pg_shared import (
    fetch_default_document_names,
    fetch_linked_documents,
    linked_document_ids,
    maybe_iso,
    maybe_json_load,
    replace_linked_documents,
    stringify_id,
    stringify_id_list,
)


def _default_exam_title(cur, file_ids: List[str]) -> str:
    """Generate a default exam title from linked documents."""
    names = fetch_default_document_names(cur, file_ids)
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - Exam"
    elif len(names) > 1:
        prefix = f"Exam from {len(names)} documents"
    else:
        prefix = "Exam"
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
    total_marks = sum(q.get("marks", 1) for q in questions)

    with _get_conn() as conn, conn.cursor() as cur:
        title = exam_name or _default_exam_title(cur, file_ids)
        cur.execute(
            """
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
        """,
            (
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
            ),
        )
        row = cur.fetchone()

        cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
        for idx, q in enumerate(questions):
            cur.execute(
                """
                INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                VALUES (%s, %s, %s, %s)
            """,
                (
                    exam_id,
                    idx,
                    json_lib.dumps(q),
                    q.get("marks", 1),
                ),
            )

        replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)

        conn.commit()

        return {
            "exam_id": str(row["id"]),
            "title": title,
            "created_at": maybe_iso(row["created_at"]),
            "num_questions": len(questions),
            "total_marks": total_marks,
        }


def get_exams_by_class(class_id: str) -> List[Dict[str, Any]]:
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

        exam_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "exam_documents", "exam_id", exam_ids)

        return [
            {
                "id": stringify_id(r["id"]),
                "title": r["title"] or "Untitled Exam",
                "description": r["description"],
                "difficulty": r["difficulty"],
                "total_marks": r["total_marks"],
                "duration_minutes": r["duration_minutes"],
                "num_questions": r["num_questions"] or 0,
                "created_at": maybe_iso(r["created_at"]),
                "updated_at": maybe_iso(r["updated_at"]),
                "is_published": r["is_published"],
                "start_at": maybe_iso(r["start_at"]),
                "end_at": maybe_iso(r["end_at"]),
                "pdf_path": r["pdf_path"],
                "owner_id": stringify_id(r["owner_id"]),
                "file_ids": stringify_id_list(r["file_ids"]),
                "documents": docs.get(stringify_id(r["id"]), []),
            }
            for r in rows
        ]


def get_exam_by_id(
    exam_id: str, user_id: Optional[str] = None, include_answers: bool = True
) -> Dict[str, Any]:
    sql = """
    SELECT id, title, description, questions_json, difficulty, total_marks, duration_minutes,
           class_id, owner_id, created_at, updated_at, is_published, pdf_path, start_at, end_at
    FROM exams WHERE id = %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id,))
        r = cur.fetchone()
        if not r:
            raise NotFoundError("Exam not found")

        documents = fetch_linked_documents(
            cur,
            "exam_documents",
            "exam_id",
            [exam_id],
            include_class_id=True,
        ).get(exam_id, [])

        cur.execute(
            """
            SELECT id, position, question_snapshot, max_marks
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY position ASC
        """,
            (exam_id,),
        )
        eq_rows = cur.fetchall()

        if user_id:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row else None

            if role == "student":
                if not r["is_published"]:
                    raise NotReleasedError()
                if r["class_id"]:
                    cur.execute(
                        "SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s",
                        (r["class_id"], user_id),
                    )
                    if not cur.fetchone():
                        raise PermissionDeniedError("Permission denied")

        if eq_rows:
            questions = []
            for eq in eq_rows:
                q_snapshot = maybe_json_load(eq["question_snapshot"], None)
                q_snapshot["exam_question_id"] = stringify_id(eq["id"])
                questions.append(q_snapshot)
        else:
            questions = maybe_json_load(r["questions_json"], [])

        if not include_answers:
            for q in questions:
                q.pop("correct_answer_index", None)
                q.pop("model_answer", None)
                q.pop("marking_scheme", None)
                q.pop("rationale", None)

        return {
            "id": stringify_id(r["id"]),
            "title": r["title"] or "Untitled Exam",
            "description": r["description"],
            "questions": questions,
            "difficulty": r["difficulty"],
            "total_marks": r["total_marks"],
            "duration_minutes": r["duration_minutes"],
            "num_questions": len(questions),
            "class_id": stringify_id(r["class_id"]),
            "owner_id": stringify_id(r["owner_id"]),
            "created_at": maybe_iso(r["created_at"]),
            "updated_at": maybe_iso(r["updated_at"]),
            "is_published": r["is_published"],
            "start_at": maybe_iso(r["start_at"]),
            "end_at": maybe_iso(r["end_at"]),
            "pdf_path": r["pdf_path"],
            "file_ids": linked_document_ids(documents),
            "documents": [
                {"id": document["id"], "name": document["name"]}
                for document in documents
            ],
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
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, questions_json FROM exams WHERE id = %s", (exam_id,))
        existing = cur.fetchone()
        if not existing:
            raise NotFoundError("Exam not found")

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
            params,
        )
        row = cur.fetchone()

        if questions is not None:
            cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
            for idx, q in enumerate(questions):
                cur.execute(
                    """
                    INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                    VALUES (%s, %s, %s, %s)
                """,
                    (
                        exam_id,
                        idx,
                        json_lib.dumps(q),
                        q.get("marks", 1),
                    ),
                )

        if file_ids is not None:
            replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)

        conn.commit()

        return {
            "exam_id": stringify_id(row["id"]),
            "title": row["title"],
            "total_marks": row["total_marks"],
        }


def delete_exam(exam_id: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM exams WHERE id = %s RETURNING id, title", (exam_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("Exam not found")
        conn.commit()
        return {"message": "Exam deleted", "exam_id": str(row["id"]), "title": row["title"]}


def publish_exam(exam_id: str, is_published: bool = True) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE exams SET is_published = %s, updated_at = now() WHERE id = %s RETURNING id, title, is_published",
            (is_published, exam_id),
        )
        row = cur.fetchone()
        if not row:
            raise NotFoundError("Exam not found")
        conn.commit()
        return {
            "exam_id": str(row["id"]),
            "title": row["title"],
            "is_published": row["is_published"],
        }



__all__ = [
    "_default_exam_title",
    "delete_exam",
    "get_exam_by_id",
    "get_exams_by_class",
    "publish_exam",
    "save_exam",
    "update_exam",
]
