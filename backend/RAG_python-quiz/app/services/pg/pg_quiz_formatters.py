# -*- coding: utf-8 -*-
"""Formatting helpers for quiz persistence responses."""

from datetime import datetime
from typing import Any, Dict, List

from app.services.pg.pg_shared import (
    filter_linked_documents,
    linked_document_ids,
    map_quiz_submission_row,
    maybe_iso,
    stringify_id,
    stringify_id_list,
)

UNTITLED_QUIZ_NAME = "Untitled Quiz"


def build_default_quiz_name(names: List[str], *, now: datetime) -> str:
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - Quiz"
    elif len(names) > 1:
        prefix = f"{len(names)} documents - Quiz"
    else:
        prefix = "Quiz"
    return f"{prefix} ({now.strftime('%m/%d %H:%M')})"


def format_quiz_summary(row: Dict[str, Any], docs: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    quiz_id = stringify_id(row["id"])
    return {
        "id": quiz_id,
        "name": row["name"] or UNTITLED_QUIZ_NAME,
        "num_questions": row["num_questions"],
        "created_at": maybe_iso(row["created_at"]),
        "file_ids": stringify_id_list(row["file_ids"]),
        "was_summarized": row["was_summarized"],
        "source_text_length": row["source_text_length"],
        "documents": [doc for doc in (docs.get(quiz_id) or []) if doc.get("id")],
    }


def format_quiz_detail(
    row: Dict[str, Any], questions: List[Dict[str, Any]], documents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "id": stringify_id(row["id"]),
        "name": row["name"] or UNTITLED_QUIZ_NAME,
        "questions": questions,
        "num_questions": row["num_questions"],
        "created_at": maybe_iso(row["created_at"]),
        "file_ids": linked_document_ids(documents),
        "was_summarized": row["was_summarized"],
        "source_text_length": row["source_text_length"],
        "documents": [
            {"id": document["id"], "name": document["name"]}
            for document in filter_linked_documents(documents)
        ],
    }


def format_quiz_submission_with_student(row: Dict[str, Any]) -> Dict[str, Any]:
    return map_quiz_submission_row(
        {
            **row,
            "student_name": row.get("full_name"),
            "student_email": row.get("email"),
        },
        include_student=True,
    )
