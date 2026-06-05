from typing import Any

from app.services.core.exceptions import PermissionDeniedError, ValidationServiceError
from app.services.pg.pg_db import (
    execute_returning,
    fetch_bool,
    fetch_bool_with_cursor,
    fetch_one_with_cursor,
    map_rows,
    with_cursor,
)
from app.utils.datetime_utils import iso


def is_user_teacher(user_id: str) -> bool:
    return fetch_bool(
        "SELECT app_security.is_teacher(%s::uuid) AS is_teacher",
        (user_id,),
        column="is_teacher",
    )


def create_class_for_teacher(
    teacher_user_id: str, name: str, code: str | None = None
) -> dict[str, Any]:
    if not name or not name.strip():
        raise ValidationServiceError("Class name must not be empty")

    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can create classes")

    row = execute_returning(
        """
        INSERT INTO classes (teacher_id, name, code)
        VALUES (%s, %s, %s)
        RETURNING id, teacher_id, name, code, created_at
        """,
        (teacher_user_id, name.strip(), code),
    )
    return _format_class(row)


def list_classes_by_teacher(teacher_user_id: str) -> list[dict[str, Any]]:
    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can view their classes")

    return map_rows(
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
        mapper=_format_teacher_class,
    )


def list_classes_for_student(student_user_id: str) -> list[dict[str, Any]]:
    if not _is_student_exists(student_user_id):
        raise PermissionDeniedError("Only students can view enrolled classes")

    return map_rows(
        """
        SELECT c.id, c.teacher_id, c.name, c.code, c.created_at,
               (SELECT COUNT(*) FROM class_students s WHERE s.class_id = c.id) AS student_count
        FROM class_students cs
        JOIN classes c ON c.id = cs.class_id
        WHERE cs.student_id = %s
        ORDER BY cs.enrolled_at DESC
        """,
        (student_user_id,),
        mapper=_format_class_with_count,
    )


def _format_class(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "teacher_id": str(row["teacher_id"]),
        "name": row["name"],
        "code": row.get("code"),
        "created_at": iso(row.get("created_at")),
    }


def _format_class_with_count(row: dict[str, Any]) -> dict[str, Any]:
    formatted = _format_class(row)
    formatted["student_count"] = int(row.get("student_count") or 0)
    return formatted


def _format_teacher_class(row: dict[str, Any]) -> dict[str, Any]:
    formatted = _format_class_with_count(row)
    formatted["students"] = row.get("students") or []
    return formatted


def _is_student_exists(user_id: str) -> bool:
    return fetch_bool(
        "SELECT app_security.is_student(%s::uuid) AS exists",
        (user_id,),
        column="exists",
    )


def invite_student_to_class(
    teacher_user_id: str, class_id: str, student_email: str
) -> dict[str, Any]:
    if not is_user_teacher(teacher_user_id):
        raise PermissionDeniedError("Only teachers can invite students to classes")
    if not student_email or not student_email.strip():
        raise ValidationServiceError("Student email must not be empty")

    with with_cursor(write=True) as cur:
        if not fetch_bool_with_cursor(
            cur,
            "SELECT app_security.is_class_owned_by_teacher(%s::uuid, %s::uuid) AS owns_class",
            (class_id, teacher_user_id),
            column="owns_class",
        ):
            raise PermissionDeniedError("Class not found or not owned by teacher")

        student = fetch_one_with_cursor(
            cur,
            "SELECT * FROM app_security.lookup_student_for_invite(%s)",
            (student_email.strip(),),
        )
        if not student:
            raise ValidationServiceError("Student does not exist")
        if student.get("role") != "student":
            raise ValidationServiceError("User is not a student")
        student_id = student.get("id")
        if not fetch_bool_with_cursor(
            cur,
            "SELECT app_security.is_student(%s::uuid) AS exists",
            (student_id,),
            column="exists",
        ):
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

