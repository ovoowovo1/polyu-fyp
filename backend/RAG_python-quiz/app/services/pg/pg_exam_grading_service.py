# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from app.services.pg.pg_db import _get_conn
from app.services.pg.pg_exam_grading_updates import (
    apply_answer_grades,
    fetch_ai_submission_for_grading,
    fetch_submission_score,
    fetch_teacher_submission_for_grading,
    finalize_ai_grade,
    finalize_teacher_grade,
    format_ai_grade_result,
    format_teacher_grade_result,
)


def grade_exam_submission(
    submission_id: str,
    teacher_id: str,
    answers_grades: Optional[List[Dict[str, Any]]] = None,
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        sub = fetch_teacher_submission_for_grading(cur, submission_id, teacher_id)
        apply_answer_grades(cur, submission_id, answers_grades, include_correct=False)
        score = fetch_submission_score(cur, submission_id)
        row = finalize_teacher_grade(
            cur,
            submission_id=submission_id,
            teacher_id=teacher_id,
            score=score,
            teacher_comment=teacher_comment,
        )
        conn.commit()
        return format_teacher_grade_result(row, sub)


def ai_grade_exam_submission(
    submission_id: str,
    graded_answers: List[Dict[str, Any]],
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        sub = fetch_ai_submission_for_grading(cur, submission_id)
        apply_answer_grades(cur, submission_id, graded_answers, include_correct=True)
        score = fetch_submission_score(cur, submission_id)
        row = finalize_ai_grade(
            cur,
            submission_id=submission_id,
            score=score,
            teacher_comment=teacher_comment,
        )
        conn.commit()
        return format_ai_grade_result(row, sub)

