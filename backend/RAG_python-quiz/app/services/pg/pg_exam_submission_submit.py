# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional, Tuple

from app.services.core.exceptions import AlreadySubmittedError, NotFoundError, PermissionDeniedError
from app.services.pg.pg_exam_submission_answers import (
    build_exam_question_indexes,
    find_exam_question,
    grade_answer,
)
from app.services.pg.pg_shared import maybe_iso, stringify_id


def normalize_submit_args(
    student_id_or_answers: str | List[Dict[str, Any]],
    answers: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    if answers is None and isinstance(student_id_or_answers, list):
        return None, student_id_or_answers
    return str(student_id_or_answers), answers or []


def fetch_submission_for_submit(cur, submission_id: str, student_id: Optional[str]) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT es.id, es.exam_id, es.student_id, es.status, e.questions_json, e.total_marks
        FROM exam_submissions es
        JOIN exams e ON e.id = es.exam_id
        WHERE es.id = %s
    """,
        (submission_id,),
    )
    sub = cur.fetchone()
    if not sub:
        raise NotFoundError("Submission not found")
    if student_id and str(sub["student_id"]) != student_id:
        raise PermissionDeniedError("Permission denied")
    if sub["status"] != "in_progress":
        raise AlreadySubmittedError()
    return sub


def fetch_exam_question_rows(cur, exam_id: str) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, position, question_snapshot, max_marks
        FROM exam_questions
        WHERE exam_id = %s
        ORDER BY position ASC
    """,
        (exam_id,),
    )
    return cur.fetchall()


def insert_graded_answers(cur, submission_id: str, answers: List[Dict[str, Any]], eq_rows: List[Dict[str, Any]]) -> int:
    eq_map_by_id, eq_map_by_q_id = build_exam_question_indexes(eq_rows)
    score = 0

    for answer in answers:
        eq = find_exam_question(answer, eq_map_by_id, eq_map_by_q_id)
        if not eq:
            continue

        _graded_answer, marks_earned, insert_payload = grade_answer(answer, eq)
        score += marks_earned

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
                *insert_payload,
            ),
        )

    return score


def finalize_submission(
    cur,
    *,
    submission_id: str,
    score: int,
    total_marks: Any,
    time_spent_seconds: Optional[int],
) -> Dict[str, Any]:
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
            total_marks,
            time_spent_seconds,
            submission_id,
        ),
    )
    return cur.fetchone()


def format_submit_result(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "submission_id": stringify_id(row["id"]),
        "submitted_at": maybe_iso(row["submitted_at"]),
        "score": row["score"],
        "total_marks": row["total_marks"],
        "status": "submitted",
    }
