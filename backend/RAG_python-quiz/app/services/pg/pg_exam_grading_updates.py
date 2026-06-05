# -*- coding: utf-8 -*-
"""Shared SQL helpers for manual and AI exam grading."""

from typing import Any, Dict, List, Optional

from app.services.core.exceptions import NotFoundError, PermissionDeniedError
from app.services.pg.pg_shared import maybe_iso, stringify_id


def fetch_teacher_submission_for_grading(cur, submission_id: str, teacher_id: str) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT es.id, es.total_marks
        FROM exam_submissions es
        JOIN exams e ON e.id = es.exam_id
        LEFT JOIN classes c ON c.id = e.class_id
        WHERE es.id = %s
          AND (e.owner_id = %s OR c.teacher_id = %s)
        """,
        (submission_id, teacher_id, teacher_id),
    )
    sub = cur.fetchone()
    if not sub:
        raise PermissionDeniedError("Permission denied")
    return sub


def fetch_ai_submission_for_grading(cur, submission_id: str) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT id, total_marks FROM exam_submissions WHERE id = %s
        """,
        (submission_id,),
    )
    sub = cur.fetchone()
    if not sub:
        raise NotFoundError("Submission not found")
    return sub


def update_answer_grade(
    cur,
    submission_id: str,
    grade: Dict[str, Any],
    *,
    include_correct: bool,
) -> None:
    answer_id = grade.get("answer_id")
    eq_id = grade.get("exam_question_id")

    if answer_id and include_correct:
        cur.execute(
            """
            UPDATE exam_answers
            SET marks_earned = %s,
                teacher_feedback = %s,
                is_correct = %s
            WHERE id = %s
            """,
            (
                grade.get("marks_earned", 0),
                grade.get("teacher_feedback"),
                grade.get("is_correct", False),
                answer_id,
            ),
        )
    elif answer_id:
        cur.execute(
            """
            UPDATE exam_answers
            SET marks_earned = %s,
                teacher_feedback = %s
            WHERE id = %s
            """,
            (
                grade.get("marks_earned", 0),
                grade.get("teacher_feedback"),
                answer_id,
            ),
        )
    elif eq_id and include_correct:
        cur.execute(
            """
            UPDATE exam_answers
            SET marks_earned = %s,
                teacher_feedback = %s,
                is_correct = %s
            WHERE submission_id = %s AND exam_question_id = %s
            """,
            (
                grade.get("marks_earned", 0),
                grade.get("teacher_feedback"),
                grade.get("is_correct", False),
                submission_id,
                eq_id,
            ),
        )
    elif eq_id:
        cur.execute(
            """
            UPDATE exam_answers
            SET marks_earned = %s,
                teacher_feedback = %s
            WHERE submission_id = %s AND exam_question_id = %s
            """,
            (
                grade.get("marks_earned", 0),
                grade.get("teacher_feedback"),
                submission_id,
                eq_id,
            ),
        )


def apply_answer_grades(
    cur,
    submission_id: str,
    grades: Optional[List[Dict[str, Any]]],
    *,
    include_correct: bool,
) -> None:
    if grades:
        for grade in grades:
            update_answer_grade(cur, submission_id, grade, include_correct=include_correct)


def fetch_submission_score(cur, submission_id: str):
    cur.execute(
        """
        SELECT COALESCE(SUM(marks_earned), 0) AS total_score
        FROM exam_answers
        WHERE submission_id = %s
        """,
        (submission_id,),
    )
    return cur.fetchone()["total_score"]


def finalize_teacher_grade(
    cur,
    *,
    submission_id: str,
    teacher_id: str,
    score,
    teacher_comment: Optional[str],
) -> Dict[str, Any]:
    cur.execute(
        """
        UPDATE exam_submissions
        SET score = %s,
            teacher_comment = COALESCE(%s, teacher_comment),
            graded_by = %s,
            graded_at = now(),
            grading_source = 'teacher',
            status = 'graded'
        WHERE id = %s
        RETURNING id, score, graded_at
        """,
        (
            score,
            teacher_comment,
            teacher_id,
            submission_id,
        ),
    )
    return cur.fetchone()


def finalize_ai_grade(
    cur,
    *,
    submission_id: str,
    score,
    teacher_comment: Optional[str],
) -> Dict[str, Any]:
    if teacher_comment:
        cur.execute(
            """
            UPDATE exam_submissions
            SET score = %s,
                graded_at = now(),
                graded_by = NULL,
                grading_source = 'ai',
                status = 'ai_graded',
                teacher_comment = %s
            WHERE id = %s
            RETURNING id, score, graded_at, status, teacher_comment
            """,
            (score, teacher_comment, submission_id),
        )
    else:
        cur.execute(
            """
            UPDATE exam_submissions
            SET score = %s,
                graded_at = now(),
                graded_by = NULL,
                grading_source = 'ai',
                status = 'ai_graded'
            WHERE id = %s
            RETURNING id, score, graded_at, status, teacher_comment
            """,
            (score, submission_id),
        )
    return cur.fetchone()


def format_teacher_grade_result(row: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "submission_id": str(row["id"]),
        "score": row["score"],
        "total_marks": sub["total_marks"],
        "graded_at": maybe_iso(row["graded_at"]),
        "status": "graded",
    }


def format_ai_grade_result(row: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "submission_id": stringify_id(row["id"]),
        "score": row["score"],
        "total_marks": sub["total_marks"],
        "graded_at": maybe_iso(row["graded_at"]),
        "status": row["status"],
        "grading_source": "ai",
        "teacher_comment": row.get("teacher_comment"),
    }
