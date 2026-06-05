from __future__ import annotations

from typing import Any, Dict, List

from app.services.core.exceptions import NotReleasedError, PermissionDeniedError
from app.services.pg.pg_shared import stringify_id


def enforce_exam_visibility(cur, exam_row: Dict[str, Any], documents: List[Dict[str, Any]], user_id: str) -> None:
    del documents
    cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    role = row["role"] if row else None

    if role == "student":
        _enforce_student_visibility(cur, exam_row, user_id)
    elif role == "teacher":
        _enforce_teacher_visibility(cur, exam_row, user_id)
    else:
        raise PermissionDeniedError("Permission denied")


def _enforce_student_visibility(cur, exam_row: Dict[str, Any], user_id: str) -> None:
    if not exam_row["is_published"]:
        raise NotReleasedError()
    if exam_row["class_id"]:
        cur.execute(
            "SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s",
            (exam_row["class_id"], user_id),
        )
        if not cur.fetchone():
            raise PermissionDeniedError("Permission denied")


def _enforce_teacher_visibility(cur, exam_row: Dict[str, Any], user_id: str) -> None:
    if stringify_id(exam_row["owner_id"]) == user_id:
        return
    if exam_row["class_id"]:
        cur.execute(
            "SELECT 1 FROM classes WHERE id = %s AND teacher_id = %s",
            (exam_row["class_id"], user_id),
        )
        if cur.fetchone():
            return
    raise PermissionDeniedError("Permission denied")
