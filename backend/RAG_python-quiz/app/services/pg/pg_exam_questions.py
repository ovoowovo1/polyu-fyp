from __future__ import annotations

import json as json_lib
from typing import Any, Dict, List

from app.services.pg.pg_shared import maybe_json_load, stringify_id


def total_marks_for_questions(questions: List[Dict[str, Any]]) -> int:
    return sum(question.get("marks", 1) for question in questions)


def replace_exam_questions(cur, exam_id: str, questions: List[Dict[str, Any]]) -> None:
    cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
    for idx, question in enumerate(questions):
        cur.execute(
            """
            INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
            VALUES (%s, %s, %s, %s)
            """,
            (
                exam_id,
                idx,
                json_lib.dumps(question),
                question.get("marks", 1),
            ),
        )


def load_exam_questions(eq_rows, fallback_questions_json) -> List[Dict[str, Any]]:
    if not eq_rows:
        return maybe_json_load(fallback_questions_json, [])

    questions = []
    for eq in eq_rows:
        question_snapshot = maybe_json_load(eq["question_snapshot"], None)
        question_snapshot["exam_question_id"] = stringify_id(eq["id"])
        questions.append(question_snapshot)
    return questions


def hide_answer_fields(questions: List[Dict[str, Any]]) -> None:
    for question in questions:
        question.pop("correct_answer_index", None)
        question.pop("model_answer", None)
        question.pop("marking_scheme", None)
        question.pop("rationale", None)
