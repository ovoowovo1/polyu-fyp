# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from app.services.exceptions import PermissionDeniedError, ValidationServiceError
from app.services.pg_db import _get_conn
from app.utils.datetime_utils import iso


def is_user_teacher(user_id: str) -> bool:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        return bool(row and (row.get("role") == "teacher"))


def create_class_for_teacher(
    teacher_user_id: str, name: str, code: Optional[str] = None
) -> Dict[str, Any]:
    if not name or not name.strip():
        raise ValidationServiceError("Class name must not be empty")

    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can create classes")

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO classes (teacher_id, name, code)
            VALUES (%s, %s, %s)
            RETURNING id, teacher_id, name, code, created_at
            """,
            (teacher_user_id, name.strip(), code),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "id": str(row["id"]),
            "teacher_id": str(row["teacher_id"]),
            "name": row["name"],
            "code": row.get("code"),
            "created_at": iso(row.get("created_at")),
        }


def list_classes_by_teacher(teacher_user_id: str) -> List[Dict[str, Any]]:
    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can view their classes")

    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.teacher_id, c.name, c.code, c.created_at,
                   COUNT(cs.student_id) AS student_count,
                   COALESCE(
                     json_agg(
                       json_build_object(
                         'id', u.id,
                         'name', u.full_name,
                         'email', u.email
                       )
                     ) FILTER (WHERE u.id IS NOT NULL),
                     '[]'
                   ) AS students
            FROM classes c
            LEFT JOIN class_students cs ON cs.class_id = c.id
            LEFT JOIN users u ON u.id = cs.student_id
            WHERE c.teacher_id = %s
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """,
            (teacher_user_id,),
        )
        rows = cur.fetchall() or []
        return [
            {
                "id": str(r["id"]),
                "teacher_id": str(r["teacher_id"]),
                "name": r["name"],
                "code": r.get("code"),
                "created_at": iso(r.get("created_at")),
                "student_count": int(r.get("student_count") or 0),
                "students": r.get("students") or [],
            }
            for r in rows
        ]


def list_classes_for_student(student_user_id: str) -> List[Dict[str, Any]]:
    with _get_conn() as conn, conn.cursor() as cur:
        if not _is_student_exists(cur, student_user_id):
            raise PermissionDeniedError("Only students can view enrolled classes")

        cur.execute(
            """
            SELECT c.id, c.teacher_id, c.name, c.code, c.created_at,
                   (SELECT COUNT(*) FROM class_students s WHERE s.class_id = c.id) AS student_count
            FROM class_students cs
            JOIN classes c ON c.id = cs.class_id
            WHERE cs.student_id = %s
            ORDER BY cs.enrolled_at DESC
            """,
            (student_user_id,),
        )
        rows = cur.fetchall() or []
        return [
            {
                "id": str(r["id"]),
                "teacher_id": str(r["teacher_id"]),
                "name": r["name"],
                "code": r.get("code"),
                "created_at": iso(r.get("created_at")),
                "student_count": int(r.get("student_count") or 0),
            }
            for r in rows
        ]


def _get_user_by_email(cur, email: str) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT id, email, full_name, role FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    return dict(row) if row else None


def _is_student_exists(cur, user_id: str) -> bool:
    cur.execute("SELECT 1 FROM students WHERE user_id=%s", (user_id,))
    return bool(cur.fetchone())


def _is_class_owned_by_teacher(cur, class_id: str, teacher_user_id: str) -> bool:
    cur.execute("SELECT 1 FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_user_id))
    return bool(cur.fetchone())


def invite_student_to_class(
    teacher_user_id: str, class_id: str, student_email: str
) -> Dict[str, Any]:
    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can invite students to classes")
    if not student_email or not student_email.strip():
        raise ValidationServiceError("Student email must not be empty")

    with _get_conn() as conn, conn.cursor() as cur:
        if not _is_class_owned_by_teacher(cur, class_id, teacher_user_id):
            raise PermissionDeniedError("Class not found or not owned by teacher")

        student = _get_user_by_email(cur, student_email.strip())
        if not student:
            raise ValidationServiceError("Student does not exist")
        if student.get("role") != "student":
            raise ValidationServiceError("User is not a student")
        student_id = student.get("id")
        if not _is_student_exists(cur, student_id):
            raise ValidationServiceError("Student profile is incomplete")

        cur.execute(
            """
            INSERT INTO class_students (class_id, student_id)
            VALUES (%s, %s)
            ON CONFLICT (class_id, student_id) DO NOTHING
            RETURNING class_id, student_id, enrolled_at
            """,
            (class_id, student_id),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            cur.execute(
                "SELECT class_id, student_id, enrolled_at FROM class_students WHERE class_id=%s AND student_id=%s",
                (class_id, student_id),
            )
            row = cur.fetchone()

        return {
            "class_id": str(row["class_id"]),
            "student_id": str(row["student_id"]),
            "enrolled_at": iso(row.get("enrolled_at")),
            "student": {
                "id": str(student_id),
                "email": student.get("email"),
                "full_name": student.get("full_name"),
            },
        }


__all__ = [
    "_get_user_by_email",
    "_is_class_owned_by_teacher",
    "_is_student_exists",
    "create_class_for_teacher",
    "invite_student_to_class",
    "is_user_teacher",
    "list_classes_by_teacher",
    "list_classes_for_student",
]
