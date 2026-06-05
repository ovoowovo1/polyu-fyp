from datetime import datetime
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.core.exceptions import NotFoundError, PermissionDeniedError, ValidationServiceError
from app.services.pg.pg_db import _get_conn, fetch_one, map_rows, require_row
from app.services.pg.pg_quiz_formatters import (
    UNTITLED_QUIZ_NAME,
    build_default_quiz_name,
    format_quiz_detail,
    format_quiz_submission_with_student,
    format_quiz_summary,
)
from app.services.pg.pg_quiz_submissions import (
    build_submission_insert_params,
    format_submission_insert_result,
)
from app.services.pg.pg_quiz_visibility import enforce_quiz_document_access, fetch_user_role
from app.services.pg.pg_shared import (
    fetch_default_document_names,
    fetch_linked_documents,
    insert_submission_with_attempt,
    maybe_json_load,
    map_quiz_submission_row,
    replace_linked_documents,
    stringify_id,
    SqlUpdateBuilder,
)


def _default_quiz_name(cur, file_ids: List[str]) -> str:
    names = fetch_default_document_names(cur, file_ids)
    return build_default_quiz_name(names, now=datetime.now())


def save_quiz(
    quiz_data: Dict[str, Any],
    file_ids: List[str],
    quiz_name: str = None,
    class_id: str = None,
) -> Dict[str, Any]:
    """Persist generated quiz questions and linked source documents."""
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
    """Update existing quiz questions, name, and linked documents."""
    if not quiz_data or "questions" not in quiz_data:
        raise ValidationServiceError("quiz_data must contain 'questions'")

    with _get_conn() as conn, conn.cursor() as cur:
        update = SqlUpdateBuilder()
        update.add_if_provided("name", name)
        update.add("questions_json = %s", json_lib.dumps(quiz_data["questions"]))
        update.add("num_questions = %s", len(quiz_data["questions"]))
        cur.execute(
            f"""
            UPDATE quizzes
            SET {update.set_clause()}
            WHERE id = %s
            RETURNING id, name
            """,
            (*update.params, quiz_id),
        )
        row = cur.fetchone()
        if not row:
            raise NotFoundError("Quiz not found")

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
            role = fetch_user_role(cur, user_id)
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

        return [_format_quiz_summary(row, docs) for row in rows]


def get_quizzes_by_class(class_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
    SELECT q.id, q.name, q.num_questions, q.created_at, q.was_summarized, q.source_text_length,
           ARRAY_AGG(DISTINCT qd.document_id)::uuid[] AS file_ids
    FROM quizzes q
    LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
    LEFT JOIN documents d ON d.id = qd.document_id
    LEFT JOIN classes cq ON cq.id = q.class_id
    LEFT JOIN classes cd ON cd.id = d.class_id
    LEFT JOIN class_students csq ON csq.class_id = q.class_id AND csq.student_id = %s
    LEFT JOIN class_students csd ON csd.class_id = d.class_id AND csd.student_id = %s
    WHERE d.class_id = %s
    """
    params: list[Any] = [user_id, user_id, class_id]
    if user_id:
        sql += """
      AND (
        cq.teacher_id = %s
        OR cd.teacher_id = %s
        OR csq.student_id IS NOT NULL
        OR csd.student_id IS NOT NULL
      )
        """
        params.extend([user_id, user_id])
    sql += """
    GROUP BY q.id
    ORDER BY q.created_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []

        quiz_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "quiz_documents", "quiz_id", quiz_ids)

        return [_format_quiz_summary(row, docs) for row in rows]


def get_quiz_by_id(quiz_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    sql = """
    SELECT id, name, questions_json, num_questions, created_at, was_summarized, source_text_length
    FROM quizzes WHERE id=%s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (quiz_id,))
        r = cur.fetchone()
        if not r:
            raise NotFoundError("Quiz not found")

        documents = fetch_linked_documents(
            cur,
            "quiz_documents",
            "quiz_id",
            [quiz_id],
            include_class_id=True,
        ).get(quiz_id, [])

        if user_id:
            enforce_quiz_document_access(cur, documents, user_id)

        questions = maybe_json_load(r["questions_json"], [])
        return _format_quiz_detail(r, questions, documents)


def delete_quiz(quiz_id: str, teacher_id: Optional[str] = None) -> Dict[str, Any]:
    if teacher_id:
        get_quiz_by_id(quiz_id, teacher_id)
    require_row(
        "DELETE FROM quizzes WHERE id=%s RETURNING id",
        (quiz_id,),
        error=NotFoundError("Quiz not found"),
        write=True,
    )
    return {"message": "Quiz deleted successfully", "quiz_id": str(quiz_id)}


def submit_quiz_result(
    quiz_id: str, student_id: str, answers: List[dict], score: int, total_questions: int
) -> dict:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM quizzes WHERE id = %s", (quiz_id,))
        if not cur.fetchone():
            raise NotFoundError("Quiz not found")

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
            build_submission_insert_params(quiz_id, student_id, answers, score, total_questions),
        )
        conn.commit()
        return format_submission_insert_result(row)


def get_quiz_submissions(quiz_id: str, teacher_id: Optional[str] = None) -> List[dict]:
    sql = """
    SELECT qs.id, qs.student_id, qs.score, qs.total_questions, qs.submitted_at,
           qs.answers_json,
           qs.attempt_no,
           u.full_name, u.email
    FROM quiz_submissions qs
    JOIN users u ON u.id = qs.student_id
    LEFT JOIN quizzes q ON q.id = qs.quiz_id
    LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
    LEFT JOIN documents d ON d.id = qd.document_id
    LEFT JOIN classes cq ON cq.id = q.class_id
    LEFT JOIN classes cd ON cd.id = d.class_id
    WHERE qs.quiz_id = %s
    """
    params: list[Any] = [quiz_id]
    if teacher_id:
        sql += """
      AND (cq.teacher_id = %s OR cd.teacher_id = %s)
        """
        params.extend([teacher_id, teacher_id])
    sql += """
    ORDER BY qs.submitted_at DESC, qs.id DESC
    """
    return map_rows(sql, tuple(params), mapper=_format_quiz_submission_with_student)


def get_student_quiz_submission(quiz_id: str, student_id: str) -> Optional[dict]:
    sql = """
    SELECT id, score, total_questions, answers_json, submitted_at
    FROM quiz_submissions
    WHERE quiz_id = %s AND student_id = %s
    """
    row = fetch_one(sql, (quiz_id, student_id))
    return map_quiz_submission_row(row) if row else None


def _format_quiz_summary(row: Dict[str, Any], docs: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return format_quiz_summary(row, docs)


def _format_quiz_detail(
    row: Dict[str, Any], questions: List[Dict[str, Any]], documents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return format_quiz_detail(row, questions, documents)


def _format_quiz_submission_with_student(row: Dict[str, Any]) -> Dict[str, Any]:
    return format_quiz_submission_with_student(row)
