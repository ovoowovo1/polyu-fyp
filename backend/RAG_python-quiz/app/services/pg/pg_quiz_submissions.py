# -*- coding: utf-8 -*-
"""Quiz submission persistence helpers."""

import json as json_lib
from typing import Any, Dict, List

from app.services.pg.pg_shared import maybe_iso, stringify_id


def build_submission_insert_params(
    quiz_id: str,
    student_id: str,
    answers: List[dict],
    score: int,
    total_questions: int,
):
    def params(attempt_no: int):
        return (
            quiz_id,
            student_id,
            score,
            total_questions,
            json_lib.dumps(answers),
            attempt_no,
        )

    return params


def format_submission_insert_result(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "submission_id": stringify_id(row["id"]),
        "submitted_at": maybe_iso(row["submitted_at"]),
        "attempt_no": row.get("attempt_no"),
    }
