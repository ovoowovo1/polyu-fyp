# -*- coding: utf-8 -*-
from datetime import datetime
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.core.exceptions import NotFoundError
from app.services.pg import pg_exam_formatters, pg_exam_questions, pg_exam_visibility
from app.services.pg.pg_access_control import require_exam_teacher
from app.services.pg.pg_db import _get_conn, require_row
from app.services.pg.pg_shared import (
    fetch_default_document_names,
    fetch_linked_documents,
    maybe_iso,
    replace_linked_documents,
    stringify_id,
    SqlUpdateBuilder,
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
    total_marks = pg_exam_questions.total_marks_for_questions(questions)

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
        pg_exam_questions.replace_exam_questions(cur, exam_id, questions)
        replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)
        conn.commit()

        return {
            "exam_id": str(row["id"]),
            "title": title,
            "created_at": maybe_iso(row["created_at"]),
            "num_questions": len(questions),
            "total_marks": total_marks,
        }


def get_exams_by_class(class_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
    SELECT e.id, e.title, e.description, e.difficulty, e.total_marks, e.duration_minutes,
           e.created_at, e.updated_at, e.is_published, e.pdf_path, e.owner_id,
           e.start_at, e.end_at,
           (SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS num_questions,
           ARRAY_AGG(DISTINCT ed.document_id)::uuid[] AS file_ids
    FROM exams e
    LEFT JOIN exam_documents ed ON ed.exam_id = e.id
    LEFT JOIN classes c ON c.id = e.class_id
    LEFT JOIN class_students cs ON cs.class_id = e.class_id AND cs.student_id = %s
    WHERE e.class_id = %s
    """
    params: list[Any] = [user_id, class_id]
    if user_id:
        sql += """
          AND (
            e.owner_id = %s
            OR c.teacher_id = %s
            OR (e.is_published = TRUE AND cs.student_id IS NOT NULL)
          )
        """
        params.extend([user_id, user_id])
    sql += """
    GROUP BY e.id
    ORDER BY e.created_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        exam_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "exam_documents", "exam_id", exam_ids)
        return [_format_exam_summary(row, docs) for row in rows]


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
        row = cur.fetchone()
        if not row:
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
        questions = pg_exam_questions.load_exam_questions(cur.fetchall(), row["questions_json"])

        if user_id:
            pg_exam_visibility.enforce_exam_visibility(cur, row, documents, user_id)
        if not include_answers:
            pg_exam_questions.hide_answer_fields(questions)

        return _format_exam_detail(row, questions, documents)


def update_exam(
    exam_id: str,
    teacher_id: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    questions: Optional[List[Dict[str, Any]]] = None,
    difficulty: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    file_ids: Optional[List[str]] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> Dict[str, Any]:
    if teacher_id:
        require_exam_teacher(teacher_id, exam_id)

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, questions_json FROM exams WHERE id = %s", (exam_id,))
        existing = cur.fetchone()
        if not existing:
            raise NotFoundError("Exam not found")

        update = SqlUpdateBuilder(["updated_at = now()"])
        update.add_if_provided("title", title)
        update.add_if_provided("description", description)
        if questions is not None:
            update.add("questions_json = %s", json_lib.dumps(questions))
            update.add("total_marks = %s", pg_exam_questions.total_marks_for_questions(questions))
        update.add_if_provided("difficulty", difficulty)
        if duration_minutes is not None:
            update.add("duration_minutes = %s", duration_minutes if duration_minutes > 0 else None)
        if start_at is not None:
            update.add("start_at = %s", start_at if start_at else None)
        if end_at is not None:
            update.add("end_at = %s", end_at if end_at else None)

        cur.execute(
            f"UPDATE exams SET {update.set_clause()} WHERE id = %s RETURNING id, title, total_marks",
            [*update.params, exam_id],
        )
        row = cur.fetchone()

        if questions is not None:
            pg_exam_questions.replace_exam_questions(cur, exam_id, questions)
        if file_ids is not None:
            replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)

        conn.commit()
        return {
            "exam_id": stringify_id(row["id"]),
            "title": row["title"],
            "total_marks": row["total_marks"],
        }


def delete_exam(exam_id: str, teacher_id: Optional[str] = None) -> Dict[str, Any]:
    if teacher_id:
        require_exam_teacher(teacher_id, exam_id)
    row = require_row(
        "DELETE FROM exams WHERE id = %s RETURNING id, title",
        (exam_id,),
        error=NotFoundError("Exam not found"),
        write=True,
    )
    return {"message": "Exam deleted", "exam_id": str(row["id"]), "title": row["title"]}


def publish_exam(
    exam_id: str,
    teacher_id: Optional[str] = None,
    is_published: bool = True,
) -> Dict[str, Any]:
    if teacher_id:
        require_exam_teacher(teacher_id, exam_id)
    row = require_row(
        "UPDATE exams SET is_published = %s, updated_at = now() WHERE id = %s RETURNING id, title, is_published",
        (is_published, exam_id),
        error=NotFoundError("Exam not found"),
        write=True,
    )
    return {
        "exam_id": str(row["id"]),
        "title": row["title"],
        "is_published": row["is_published"],
    }


def _format_exam_summary(
    row: Dict[str, Any], docs: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    return pg_exam_formatters.format_exam_summary(row, docs)


def _format_exam_detail(
    row: Dict[str, Any], questions: List[Dict[str, Any]], documents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return pg_exam_formatters.format_exam_detail(row, questions, documents)
