# -*- coding: utf-8 -*-
import json as json_lib
from typing import Any, Mapping, Optional, Sequence

import psycopg2.extras

from app.config import EmbeddingColumn, get_settings
from app.utils.datetime_utils import iso


VALID_EMBEDDING_COLUMNS = {"embedding", "embedding_v2"}


def _to_pgvector(vec: Sequence[float]) -> str:
    # 轉成 pgvector 文本字面量，如 "[0.1,0.2,...]"
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def _get_embedding_column(column: Optional[str] = None) -> EmbeddingColumn:
    resolved = column or get_settings().embedding_active_column
    if resolved not in VALID_EMBEDDING_COLUMNS:
        raise ValueError(f"Unsupported embedding column: {resolved}")
    return resolved


def maybe_json_load(value: Any, default: Any = None, *, swallow_errors: bool = False) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json_lib.loads(value)
        except Exception:
            if swallow_errors:
                return default
            raise
    return value


def maybe_iso(value: Any) -> Optional[str]:
    return iso(value) if value is not None else None


def stringify_id(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def stringify_id_list(values: Optional[Sequence[Any]]) -> list[str]:
    return [str(value) for value in (values or []) if value is not None]


def filter_linked_documents(documents: Optional[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    return [dict(document) for document in (documents or []) if document.get("id") is not None]


def linked_document_ids(documents: Optional[Sequence[Mapping[str, Any]]]) -> list[str]:
    return [document["id"] for document in filter_linked_documents(documents)]


def map_document_row(row: Mapping[str, Any], *, include_class_id: bool = False) -> dict[str, Any]:
    document = {
        "id": stringify_id(row.get("id")),
        "name": row.get("name"),
    }
    if include_class_id:
        document["class_id"] = stringify_id(row.get("class_id"))
    return document


def map_exam_answer_row(
    row: Mapping[str, Any], *, include_attachments: bool = False
) -> dict[str, Any]:
    answer = {
        "id": stringify_id(row.get("id")),
        "exam_question_id": stringify_id(row.get("exam_question_id")),
        "question_snapshot": maybe_json_load(row.get("question_snapshot"), None),
        "answer_text": row.get("answer_text"),
        "selected_options": maybe_json_load(row.get("selected_options"), None),
        "time_spent_seconds": row.get("time_spent_seconds"),
        "is_correct": row.get("is_correct"),
        "marks_earned": row.get("marks_earned"),
        "teacher_feedback": row.get("teacher_feedback"),
    }
    if include_attachments:
        answer["attachments"] = maybe_json_load(
            row.get("attachments"), [], swallow_errors=True
        ) or []
    return answer


def fetch_default_document_names(cur, file_ids: Sequence[str], limit: int = 3) -> list[str]:
    cur.execute(
        f"SELECT name FROM documents WHERE id = ANY(%s::uuid[]) LIMIT {int(limit)}",
        (list(file_ids),),
    )
    return [row["name"] for row in cur.fetchall()]


def fetch_linked_documents(
    cur,
    table_name: str,
    owner_column: str,
    owner_ids: Sequence[Any],
    *,
    include_class_id: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    if not owner_ids:
        return {}

    class_id_select = ", d.class_id" if include_class_id else ""
    cur.execute(
        f"""
        SELECT links.{owner_column} AS owner_id, d.id, d.name{class_id_select}
        FROM {table_name} links
        JOIN documents d ON d.id = links.document_id
        WHERE links.{owner_column} = ANY(%s::uuid[])
        """,
        (list(owner_ids),),
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        owner_value = row.get("owner_id", row.get(owner_column))
        if owner_value is None and len(owner_ids) == 1:
            owner_value = owner_ids[0]
        owner_id = stringify_id(owner_value)
        grouped.setdefault(owner_id, []).append(
            map_document_row(row, include_class_id=include_class_id)
        )
    return grouped


def replace_linked_documents(
    cur, table_name: str, owner_column: str, owner_id: str, file_ids: Sequence[str]
) -> None:
    cur.execute(f"DELETE FROM {table_name} WHERE {owner_column} = %s", (owner_id,))
    if not file_ids:
        return
    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO {table_name} ({owner_column}, document_id) VALUES %s ON CONFLICT DO NOTHING",
        [(owner_id, file_id) for file_id in file_ids],
    )


def next_attempt_no(cur, table_name: str, owner_filters: Mapping[str, Any]) -> int:
    where_clause = " AND ".join(f"{column} = %s" for column in owner_filters)
    cur.execute(
        f"SELECT COALESCE(MAX(attempt_no), 0) AS max_attempt FROM {table_name} WHERE {where_clause}",
        tuple(owner_filters.values()),
    )
    row = cur.fetchone() or {}
    return int(row.get("max_attempt") or 0) + 1


def insert_submission_with_attempt(
    cur,
    table_name: str,
    owner_filters: Mapping[str, Any],
    insert_sql: str,
    params_factory,
):
    attempt_no = next_attempt_no(cur, table_name, owner_filters)
    cur.execute(insert_sql, params_factory(attempt_no))
    return cur.fetchone(), attempt_no


def map_quiz_submission_row(
    row: Mapping[str, Any],
    *,
    include_student: bool = False,
) -> dict[str, Any]:
    submission = {
        "submission_id": stringify_id(row.get("id")),
        "score": row.get("score"),
        "total_questions": row.get("total_questions"),
        "submitted_at": maybe_iso(row.get("submitted_at")),
        "answers": maybe_json_load(row.get("answers_json"), [], swallow_errors=True) or [],
        "attempt_no": row.get("attempt_no"),
    }
    if include_student:
        submission["student_id"] = stringify_id(row.get("student_id"))
        submission["student_name"] = row.get("student_name", row.get("full_name"))
        submission["student_email"] = row.get("student_email", row.get("email"))
    return submission


def map_exam_submission_row(
    row: Mapping[str, Any],
    *,
    answers: Optional[Sequence[Mapping[str, Any]]] = None,
    include_student: bool = False,
    include_graded_by: bool = False,
    include_grading_source: bool = False,
) -> dict[str, Any]:
    submission = {
        "submission_id": stringify_id(row.get("id")),
        "attempt_no": row.get("attempt_no"),
        "score": row.get("score"),
        "total_marks": row.get("total_marks"),
        "time_spent_seconds": row.get("time_spent_seconds"),
        "status": row.get("status"),
        "started_at": maybe_iso(row.get("started_at")),
        "submitted_at": maybe_iso(row.get("submitted_at")),
        "teacher_comment": row.get("teacher_comment"),
        "graded_at": maybe_iso(row.get("graded_at")),
        "meta": maybe_json_load(row.get("meta"), {}) or {},
        "answers": list(answers or []),
    }
    if include_student:
        submission["student_id"] = stringify_id(row.get("student_id"))
        submission["student_name"] = row.get("student_name")
        submission["student_email"] = row.get("student_email")
    if include_graded_by:
        submission["graded_by"] = stringify_id(row.get("graded_by"))
    if include_grading_source:
        submission["exam_id"] = stringify_id(row.get("exam_id"))
        submission["student_id"] = stringify_id(row.get("student_id"))
        submission["graded_by"] = stringify_id(row.get("graded_by"))
        submission["grading_source"] = row.get("grading_source")
    return submission


__all__ = [
    "VALID_EMBEDDING_COLUMNS",
    "_get_embedding_column",
    "_to_pgvector",
    "fetch_default_document_names",
    "fetch_linked_documents",
    "filter_linked_documents",
    "insert_submission_with_attempt",
    "linked_document_ids",
    "map_document_row",
    "map_exam_answer_row",
    "map_exam_submission_row",
    "map_quiz_submission_row",
    "maybe_iso",
    "maybe_json_load",
    "next_attempt_no",
    "replace_linked_documents",
    "stringify_id",
    "stringify_id_list",
]
