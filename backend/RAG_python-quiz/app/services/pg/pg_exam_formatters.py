from __future__ import annotations

from typing import Any, Dict, List

from app.services.pg.pg_shared import linked_document_ids, maybe_iso, stringify_id, stringify_id_list


def format_exam_summary(
    row: Dict[str, Any], docs: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    exam_id = stringify_id(row["id"])
    return {
        "id": exam_id,
        "title": row["title"] or "Untitled Exam",
        "description": row["description"],
        "difficulty": row["difficulty"],
        "total_marks": row["total_marks"],
        "duration_minutes": row["duration_minutes"],
        "num_questions": row["num_questions"] or 0,
        "created_at": maybe_iso(row["created_at"]),
        "updated_at": maybe_iso(row["updated_at"]),
        "is_published": row["is_published"],
        "start_at": maybe_iso(row["start_at"]),
        "end_at": maybe_iso(row["end_at"]),
        "pdf_path": row["pdf_path"],
        "owner_id": stringify_id(row["owner_id"]),
        "file_ids": stringify_id_list(row["file_ids"]),
        "documents": docs.get(exam_id, []),
    }


def format_exam_detail(
    row: Dict[str, Any], questions: List[Dict[str, Any]], documents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "id": stringify_id(row["id"]),
        "title": row["title"] or "Untitled Exam",
        "description": row["description"],
        "questions": questions,
        "difficulty": row["difficulty"],
        "total_marks": row["total_marks"],
        "duration_minutes": row["duration_minutes"],
        "num_questions": len(questions),
        "class_id": stringify_id(row["class_id"]),
        "owner_id": stringify_id(row["owner_id"]),
        "created_at": maybe_iso(row["created_at"]),
        "updated_at": maybe_iso(row["updated_at"]),
        "is_published": row["is_published"],
        "start_at": maybe_iso(row["start_at"]),
        "end_at": maybe_iso(row["end_at"]),
        "pdf_path": row["pdf_path"],
        "file_ids": linked_document_ids(documents),
        "documents": [{"id": document["id"], "name": document["name"]} for document in documents],
    }
