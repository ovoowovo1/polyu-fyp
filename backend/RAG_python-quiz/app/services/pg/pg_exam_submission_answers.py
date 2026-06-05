# -*- coding: utf-8 -*-
"""Answer mapping and scoring helpers for exam submissions."""

import json as json_lib
from typing import Any, Dict, List, Optional, Tuple

from app.services.pg.pg_shared import map_exam_answer_row, maybe_json_load, stringify_id


def fetch_exam_answers_map(cur, submission_ids: List[str], *, include_attachments: bool = False):
    if not submission_ids:
        return {}

    attachment_select = ", ea.attachments" if include_attachments else ""
    cur.execute(
        f"""
        SELECT ea.submission_id, ea.id, ea.exam_question_id, ea.question_snapshot,
               ea.answer_text, ea.selected_options, ea.time_spent_seconds,
               ea.is_correct, ea.marks_earned, ea.teacher_feedback{attachment_select}
        FROM exam_answers ea
        JOIN exam_questions eq ON ea.exam_question_id = eq.id
        WHERE ea.submission_id = ANY(%s::uuid[])
        ORDER BY eq.position ASC
        """,
        (submission_ids,),
    )

    answers_map = {}
    for row in cur.fetchall():
        submission_value = row.get("submission_id")
        if submission_value is None and len(submission_ids) == 1:
            submission_value = submission_ids[0]
        submission_key = stringify_id(submission_value)
        answers_map.setdefault(submission_key, []).append(
            map_exam_answer_row(row, include_attachments=include_attachments)
        )
    return answers_map


def build_exam_question_indexes(eq_rows: List[Dict[str, Any]]):
    by_id = {stringify_id(eq["id"]): eq for eq in eq_rows}
    by_question_id = {}
    for eq in eq_rows:
        snapshot = maybe_json_load(eq["question_snapshot"], None)
        q_id = snapshot.get("question_id")
        if q_id:
            by_question_id[q_id] = eq
    return by_id, by_question_id


def find_exam_question(
    answer: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    by_question_id: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    eq_id = answer.get("exam_question_id")
    q_id = answer.get("question_id")
    if eq_id:
        return by_id.get(eq_id)
    if q_id:
        return by_question_id.get(q_id)
    return None


def selected_options_for_storage(answer: Dict[str, Any]):
    selected_options = answer.get("selected_options")
    if selected_options is None and answer.get("answer_index") is not None:
        selected_options = [answer.get("answer_index")]
    return selected_options


def grade_answer(answer: Dict[str, Any], eq: Dict[str, Any]) -> Tuple[Dict[str, Any], int, tuple]:
    snapshot = maybe_json_load(eq["question_snapshot"], None)
    is_correct = False
    marks_earned = 0

    if snapshot.get("question_type") == "multiple_choice":
        correct_idx = snapshot.get("correct_answer_index")
        user_idx = answer.get("answer_index")
        if user_idx is None and answer.get("selected_options"):
            selected = answer.get("selected_options")
            if isinstance(selected, list) and len(selected) > 0:
                user_idx = selected[0]

        is_correct = correct_idx is not None and user_idx == correct_idx
        marks_earned = eq["max_marks"] if is_correct else 0

    graded_answer = {
        **answer,
        "exam_question_id": stringify_id(eq["id"]),
        "is_correct": is_correct,
        "marks_earned": marks_earned,
    }

    selected_options = selected_options_for_storage(answer)
    insert_params = (
        eq["id"],
        json_lib.dumps(snapshot),
        answer.get("answer_text"),
        json_lib.dumps(selected_options) if selected_options else None,
        answer.get("time_spent_seconds"),
        is_correct,
        marks_earned,
    )
    return graded_answer, marks_earned, insert_params
