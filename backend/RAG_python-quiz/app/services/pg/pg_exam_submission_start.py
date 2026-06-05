# -*- coding: utf-8 -*-
"""Start-submission guard helpers."""

from app.services.core.exceptions import NotFoundError, NotReleasedError, PermissionDeniedError


def fetch_released_exam_for_student(cur, exam_id: str, student_id: str):
    cur.execute(
        "SELECT id, class_id, is_published, duration_minutes, start_at, end_at FROM exams WHERE id = %s",
        (exam_id,),
    )
    exam = cur.fetchone()
    if not exam:
        raise NotFoundError("Exam not found")
    if not exam["is_published"]:
        raise NotReleasedError()
    cur.execute(
        "SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s",
        (exam["class_id"], student_id),
    )
    if not cur.fetchone():
        raise PermissionDeniedError("Permission denied")
    return exam
