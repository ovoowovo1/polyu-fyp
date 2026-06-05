# -*- coding: utf-8 -*-
"""Row mapping helpers for exam submission reads."""

from typing import Any, Dict, List

from app.services.pg.pg_shared import map_exam_submission_row, stringify_id


def map_submission_rows(
    rows: List[Dict[str, Any]],
    answers_map: Dict[str, List[Dict[str, Any]]],
    **options: Any,
) -> List[Dict[str, Any]]:
    return [
        map_exam_submission_row(
            row,
            answers=answers_map.get(stringify_id(row["id"]), []),
            **options,
        )
        for row in rows
    ]
