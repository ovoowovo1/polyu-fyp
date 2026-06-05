# -*- coding: utf-8 -*-
"""Access checks for quiz reads."""

from typing import Any, Dict, List, Optional

from app.services.core.exceptions import PermissionDeniedError


def fetch_user_role(cur, user_id: str) -> Optional[str]:
    cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    return row["role"] if row and row.get("role") else None


def enforce_quiz_document_access(cur, documents: List[Dict[str, Any]], user_id: str) -> None:
    role = fetch_user_role(cur, user_id)
    class_ids = [d["class_id"] for d in documents if d.get("class_id")]
    allowed = False

    if class_ids and role == "teacher":
        cur.execute(
            "SELECT 1 FROM classes WHERE id = ANY(%s::uuid[]) AND teacher_id = %s LIMIT 1",
            (class_ids, user_id),
        )
        allowed = bool(cur.fetchone())
    elif class_ids:
        cur.execute(
            "SELECT 1 FROM class_students WHERE class_id = ANY(%s::uuid[]) AND student_id = %s LIMIT 1",
            (class_ids, user_id),
        )
        allowed = bool(cur.fetchone())

    if not allowed:
        raise PermissionDeniedError("Permission denied")
