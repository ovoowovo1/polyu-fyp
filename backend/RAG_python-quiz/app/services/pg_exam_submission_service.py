# -*- coding: utf-8 -*-
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.exceptions import AlreadySubmittedError, NotFoundError, NotReleasedError
from app.services.pg_db import _get_conn
from app.services.pg_shared import (
    insert_submission_with_attempt,
    map_exam_answer_row,
    map_exam_submission_row,
    maybe_iso,
    maybe_json_load,
    stringify_id,
)


def _fetch_exam_answers_map(cur, submission_ids: List[str], *, include_attachments: bool = False):
    if not submission_ids:
        return {}

    attachment_select = ", ea.attachments" if include_attachments else ""
    cur.execute(
        f"""
        SELECT ea.submission_id, ea.id, ea.exam_question_id, ea.question_snapshot,
               ea.answer_text, ea.selected_options, ea.time_spent_seconds,
               ea.is_correct, ea.marks_earned, ea.teacher_feedback{attachment_select}
        FROM exam_answers ea
        JOIN exam_questions eq ON ea.exam_question_id = eq.id
        WHERE ea.submission_id = ANY(%s::uuid[])
        ORDER BY eq.position ASC
        """,
        (submission_ids,),
    )

    answers_map = {}
    for row in cur.fetchall():
        submission_value = row.get("submission_id")
        if submission_value is None and len(submission_ids) == 1:
            submission_value = submission_ids[0]
        submission_key = stringify_id(submission_value)
        answers_map.setdefault(submission_key, []).append(
            map_exam_answer_row(row, include_attachments=include_attachments)
        )
    return answers_map


def start_exam_submission(
    exam_id: str, student_id: str, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, is_published, duration_minutes, start_at, end_at FROM exams WHERE id = %s",
            (exam_id,),
        )
        exam = cur.fetchone()
        if not exam:
            raise NotFoundError("Exam not found")
        if not exam["is_published"]:
            raise NotReleasedError()

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
    answers: List[Dict[str, Any]],
    time_spent_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT es.id, es.exam_id, es.status, e.questions_json, e.total_marks
            FROM exam_submissions es
            JOIN exams e ON e.id = es.exam_id
            WHERE es.id = %s
        """,
            (submission_id,),
        )
        sub = cur.fetchone()
        if not sub:
            raise NotFoundError("Submission not found")
        if sub["status"] != "in_progress":
            raise AlreadySubmittedError()

        exam_id = sub["exam_id"]
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

        eq_map_by_id = {stringify_id(eq["id"]): eq for eq in eq_rows}
        eq_map_by_q_id = {}
        for eq in eq_rows:
            snapshot = maybe_json_load(eq["question_snapshot"], None)
            q_id = snapshot.get("question_id")
            if q_id:
                eq_map_by_q_id[q_id] = eq

        score = 0
        graded_answers = []

        for ans in answers:
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

            snapshot = maybe_json_load(eq["question_snapshot"], None)

            is_correct = False
            marks_earned = 0

            if snapshot.get("question_type") == "multiple_choice":
                correct_idx = snapshot.get("correct_answer_index")
                user_idx = ans.get("answer_index")
                if user_idx is None and ans.get("selected_options"):
                    selected = ans.get("selected_options")
                    if isinstance(selected, list) and len(selected) > 0:
                        user_idx = selected[0]

                is_correct = correct_idx is not None and user_idx == correct_idx
                marks_earned = eq["max_marks"] if is_correct else 0

            graded_answer = {
                **ans,
                "exam_question_id": stringify_id(eq["id"]),
                "is_correct": is_correct,
                "marks_earned": marks_earned,
            }
            graded_answers.append(graded_answer)
            score += marks_earned

            selected_options = ans.get("selected_options")
            if selected_options is None and ans.get("answer_index") is not None:
                selected_options = [ans.get("answer_index")]

            cur.execute(
                """
                INSERT INTO exam_answers (
                    submission_id, exam_question_id, question_snapshot,
                    answer_text, selected_options, time_spent_seconds,
                    is_correct, marks_earned
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    submission_id,
                    eq["id"],
                    json_lib.dumps(snapshot),
                    ans.get("answer_text"),
                    json_lib.dumps(selected_options) if selected_options else None,
                    ans.get("time_spent_seconds"),
                    is_correct,
                    marks_earned,
                ),
            )

        cur.execute(
            """
            UPDATE exam_submissions
            SET score = %s,
                total_marks = %s,
                time_spent_seconds = %s,
                status = 'submitted',
                submitted_at = now()
            WHERE id = %s
            RETURNING id, submitted_at, score, total_marks
        """,
            (
                score,
                sub["total_marks"],
                time_spent_seconds,
                submission_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        return {
            "submission_id": stringify_id(row["id"]),
            "submitted_at": maybe_iso(row["submitted_at"]),
            "score": row["score"],
            "total_marks": row["total_marks"],
            "status": "submitted",
        }


def get_exam_submissions(exam_id: str) -> List[Dict[str, Any]]:
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
        submission_ids = [r["id"] for r in rows]
        answers_map = _fetch_exam_answers_map(
            cur, submission_ids, include_attachments=True
        )
        return [
            map_exam_submission_row(
                row,
                answers=answers_map.get(stringify_id(row["id"]), []),
                include_student=True,
                include_graded_by=True,
            )
            for row in rows
        ]


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
        return [
            map_exam_submission_row(
                row,
                answers=answers_map.get(stringify_id(row["id"]), []),
            )
            for row in rows
        ]


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


__all__ = [
    "_fetch_exam_answers_map",
    "get_exam_submissions",
    "get_student_exam_submissions",
    "get_submission_with_answers",
    "start_exam_submission",
    "submit_exam",
]
