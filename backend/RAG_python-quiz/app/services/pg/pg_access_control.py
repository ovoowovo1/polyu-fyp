# -*- coding: utf-8 -*-
from typing import Iterable

from app.services.core.exceptions import PermissionDeniedError
from app.services.pg.pg_db import fetch_bool


def is_user_student(user_id: str) -> bool:
    return fetch_bool(
        "SELECT app_security.is_student(%s::uuid) AS is_student",
        (user_id,),
        column="is_student",
    )


def can_access_class(user_id: str, class_id: str) -> bool:
    return fetch_bool(
        """
        SELECT (
            EXISTS (
                SELECT 1 FROM classes
                WHERE id = %s::uuid AND teacher_id = %s::uuid
            )
            OR EXISTS (
                SELECT 1 FROM class_students
                WHERE class_id = %s::uuid AND student_id = %s::uuid
            )
        ) AS can_access
        """,
        (class_id, user_id, class_id, user_id),
        column="can_access",
    )


def require_class_teacher(user_id: str, class_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1 FROM classes
            WHERE id = %s::uuid AND teacher_id = %s::uuid
        ) AS owns_class
        """,
        (class_id, user_id),
        column="owns_class",
    ):
        raise PermissionDeniedError("Permission denied")


def can_access_document(user_id: str, file_id: str) -> bool:
    return fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM documents d
            LEFT JOIN classes c ON c.id = d.class_id
            LEFT JOIN class_students cs ON cs.class_id = d.class_id AND cs.student_id = %s::uuid
            WHERE d.id = %s::uuid
              AND d.class_id IS NOT NULL
              AND (c.teacher_id = %s::uuid OR cs.student_id IS NOT NULL)
        ) AS can_access
        """,
        (user_id, file_id, user_id),
        column="can_access",
    )


def require_document_teacher(user_id: str, file_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM documents d
            JOIN classes c ON c.id = d.class_id
            WHERE d.id = %s::uuid AND c.teacher_id = %s::uuid
        ) AS owns_document
        """,
        (file_id, user_id),
        column="owns_document",
    ):
        raise PermissionDeniedError("Permission denied")


def can_access_chunk(user_id: str, chunk_id: str) -> bool:
    return fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM chunks ch
            JOIN documents d ON d.id = ch.document_id
            LEFT JOIN classes c ON c.id = d.class_id
            LEFT JOIN class_students cs ON cs.class_id = d.class_id AND cs.student_id = %s::uuid
            WHERE ch.id = %s::uuid
              AND d.class_id IS NOT NULL
              AND (c.teacher_id = %s::uuid OR cs.student_id IS NOT NULL)
        ) AS can_access
        """,
        (user_id, chunk_id, user_id),
        column="can_access",
    )


def can_access_exam(user_id: str, exam_id: str) -> bool:
    return fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM exams e
            LEFT JOIN classes c ON c.id = e.class_id
            LEFT JOIN class_students cs ON cs.class_id = e.class_id AND cs.student_id = %s::uuid
            WHERE e.id = %s::uuid
              AND (
                e.owner_id = %s::uuid
                OR c.teacher_id = %s::uuid
                OR (e.is_published = TRUE AND cs.student_id IS NOT NULL)
              )
        ) AS can_access
        """,
        (user_id, exam_id, user_id, user_id),
        column="can_access",
    )


def require_exam_teacher(user_id: str, exam_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM exams e
            LEFT JOIN classes c ON c.id = e.class_id
            WHERE e.id = %s::uuid
              AND (e.owner_id = %s::uuid OR c.teacher_id = %s::uuid)
        ) AS owns_exam
        """,
        (exam_id, user_id, user_id),
        column="owns_exam",
    ):
        raise PermissionDeniedError("Permission denied")


def require_submission_owner(student_id: str, submission_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1 FROM exam_submissions
            WHERE id = %s::uuid AND student_id = %s::uuid
        ) AS owns_submission
        """,
        (submission_id, student_id),
        column="owns_submission",
    ):
        raise PermissionDeniedError("Permission denied")


def require_submission_teacher(teacher_id: str, submission_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM exam_submissions es
            JOIN exams e ON e.id = es.exam_id
            LEFT JOIN classes c ON c.id = e.class_id
            WHERE es.id = %s::uuid
              AND (e.owner_id = %s::uuid OR c.teacher_id = %s::uuid)
        ) AS owns_submission
        """,
        (submission_id, teacher_id, teacher_id),
        column="owns_submission",
    ):
        raise PermissionDeniedError("Permission denied")


def can_access_quiz(user_id: str, quiz_id: str) -> bool:
    return fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM quizzes q
            LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
            LEFT JOIN documents d ON d.id = qd.document_id
            LEFT JOIN classes cq ON cq.id = q.class_id
            LEFT JOIN classes cd ON cd.id = d.class_id
            LEFT JOIN class_students csq ON csq.class_id = q.class_id AND csq.student_id = %s::uuid
            LEFT JOIN class_students csd ON csd.class_id = d.class_id AND csd.student_id = %s::uuid
            WHERE q.id = %s::uuid
              AND (
                cq.teacher_id = %s::uuid
                OR cd.teacher_id = %s::uuid
                OR csq.student_id IS NOT NULL
                OR csd.student_id IS NOT NULL
              )
        ) AS can_access
        """,
        (user_id, user_id, quiz_id, user_id, user_id),
        column="can_access",
    )


def require_quiz_teacher(user_id: str, quiz_id: str) -> None:
    if not fetch_bool(
        """
        SELECT EXISTS (
            SELECT 1
            FROM quizzes q
            LEFT JOIN quiz_documents qd ON qd.quiz_id = q.id
            LEFT JOIN documents d ON d.id = qd.document_id
            LEFT JOIN classes cq ON cq.id = q.class_id
            LEFT JOIN classes cd ON cd.id = d.class_id
            WHERE q.id = %s::uuid
              AND (cq.teacher_id = %s::uuid OR cd.teacher_id = %s::uuid)
        ) AS owns_quiz
        """,
        (quiz_id, user_id, user_id),
        column="owns_quiz",
    ):
        raise PermissionDeniedError("Permission denied")


def can_manage_documents(user_id: str, file_ids: Iterable[str]) -> bool:
    ids = list(file_ids or [])
    if not ids:
        return False
    row_count = fetch_bool(
        """
        SELECT (
            SELECT COUNT(DISTINCT d.id)
            FROM documents d
            JOIN classes c ON c.id = d.class_id
            WHERE d.id = ANY(%s::uuid[]) AND c.teacher_id = %s::uuid
        ) = %s AS can_manage
        """,
        (ids, user_id, len(set(ids))),
        column="can_manage",
    )
    return row_count


__all__ = [
    "can_access_chunk",
    "can_access_class",
    "can_access_document",
    "can_access_exam",
    "can_access_quiz",
    "can_manage_documents",
    "is_user_student",
    "require_class_teacher",
    "require_document_teacher",
    "require_exam_teacher",
    "require_quiz_teacher",
    "require_submission_owner",
    "require_submission_teacher",
]
