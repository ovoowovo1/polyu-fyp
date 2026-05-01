# -*- coding: utf-8 -*-
"""Compatibility facade for exam persistence services."""

from app.services.pg_exam_crud import (
    _default_exam_title,
    delete_exam,
    get_exam_by_id,
    get_exams_by_class,
    publish_exam,
    save_exam,
    update_exam,
)
from app.services.pg_exam_grading_service import (
    ai_grade_exam_submission,
    grade_exam_submission,
)
from app.services.pg_exam_submission_service import (
    get_exam_submissions,
    get_student_exam_submissions,
    get_submission_with_answers,
    start_exam_submission,
    submit_exam,
)

__all__ = [
    "_default_exam_title",
    "ai_grade_exam_submission",
    "delete_exam",
    "get_exam_by_id",
    "get_exam_submissions",
    "get_exams_by_class",
    "get_student_exam_submissions",
    "get_submission_with_answers",
    "grade_exam_submission",
    "publish_exam",
    "save_exam",
    "start_exam_submission",
    "submit_exam",
    "update_exam",
]
