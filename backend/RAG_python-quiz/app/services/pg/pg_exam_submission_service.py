# -*- coding: utf-8 -*-
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.pg.pg_db import _get_conn
from app.services.pg.pg_exam_submission_answers import (
    fetch_exam_answers_map,
)
from app.services.pg.pg_exam_submission_rows import map_submission_rows
from app.services.pg.pg_exam_submission_start import fetch_released_exam_for_student
from app.services.pg.pg_exam_submission_submit import (
    fetch_exam_question_rows,
    fetch_submission_for_submit,
    finalize_submission,
    format_submit_result,
    insert_graded_answers,
    normalize_submit_args,
)
from app.services.pg.pg_shared import (
    insert_submission_with_attempt,
    map_exam_submission_row,
    maybe_iso,
    stringify_id,
)


def _fetch_exam_answers_map(cur, submission_ids: List[str], *, include_attachments: bool = False):
    return fetch_exam_answers_map(cur, submission_ids, include_attachments=include_attachments)


def start_exam_submission(
    exam_id: str, student_id: str, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        exam = fetch_released_exam_for_student(cur, exam_id, student_id)
        row, _attempt_no = insert_submission_with_attempt(
            cur,
            "exam_submissions",
            {"exam_id": exam_id, "student_id": student_id},
            """
            INSERT INTO exam_submissions (exam_id, student_id, attempt_no, status, meta)
            VALUES (%s, %s, %s, 'in_progress', %s)
            RETURNING id, started_at, attempt_no
        """,
            lambda attempt_no: (
                exam_id,
                student_id,
                attempt_no,
                json_lib.dumps(meta or {}),
            ),
        )
        conn.commit()

        return {
            "submission_id": stringify_id(row["id"]),
            "started_at": maybe_iso(row["started_at"]),
            "attempt_no": row["attempt_no"],
            "duration_minutes": exam["duration_minutes"],
        }


def submit_exam(
    submission_id: str,
    student_id_or_answers: str | List[Dict[str, Any]],
    answers: Optional[List[Dict[str, Any]]] = None,
    time_spent_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    student_id, normalized_answers = normalize_submit_args(student_id_or_answers, answers)

    with _get_conn() as conn, conn.cursor() as cur:
        sub = fetch_submission_for_submit(cur, submission_id, student_id)
        eq_rows = fetch_exam_question_rows(cur, sub["exam_id"])
        score = insert_graded_answers(cur, submission_id, normalized_answers, eq_rows)
        row = finalize_submission(
            cur,
            submission_id=submission_id,
            score=score,
            total_marks=sub["total_marks"],
            time_spent_seconds=time_spent_seconds,
        )
        conn.commit()
        return format_submit_result(row)


def get_exam_submissions(exam_id: str, teacher_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
    SELECT es.id, es.student_id, es.attempt_no, es.score, es.total_marks,
           es.time_spent_seconds, es.status, es.started_at, es.submitted_at,
           es.teacher_comment, es.graded_by, es.graded_at, es.meta,
           u.full_name AS student_name, u.email AS student_email
    FROM exam_submissions es
    JOIN users u ON u.id = es.student_id
    JOIN exams e ON e.id = es.exam_id
    LEFT JOIN classes c ON c.id = e.class_id
    WHERE es.exam_id = %s
    """
    params: list[Any] = [exam_id]
    if teacher_id:
        sql += """
      AND (e.owner_id = %s OR c.teacher_id = %s)
        """
        params.extend([teacher_id, teacher_id])
    sql += """
    ORDER BY es.submitted_at DESC NULLS LAST, es.started_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        submission_ids = [r["id"] for r in rows]
        answers_map = _fetch_exam_answers_map(
            cur, submission_ids, include_attachments=True
        )
        return _map_submission_rows(
            rows,
            answers_map,
            include_student=True,
            include_graded_by=True,
        )


def get_student_exam_submissions(exam_id: str, student_id: str) -> List[Dict[str, Any]]:
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
        submission_ids = [r["id"] for r in rows]
        answers_map = _fetch_exam_answers_map(cur, submission_ids)
        return _map_submission_rows(rows, answers_map)


def get_submission_with_answers(submission_id: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, exam_id, student_id, score, total_marks, status,
                   started_at, submitted_at, teacher_comment, graded_at, graded_by,
                   grading_source, meta
            FROM exam_submissions
            WHERE id = %s
        """,
            (submission_id,),
        )
        sub = cur.fetchone()

        if not sub:
            return None

        answers_map = _fetch_exam_answers_map(cur, [submission_id])
        return map_exam_submission_row(
            sub,
            answers=answers_map.get(submission_id, []),
            include_grading_source=True,
        )


def _map_submission_rows(
    rows: List[Dict[str, Any]],
    answers_map: Dict[str, List[Dict[str, Any]]],
    **options: Any,
) -> List[Dict[str, Any]]:
    return map_submission_rows(rows, answers_map, **options)

