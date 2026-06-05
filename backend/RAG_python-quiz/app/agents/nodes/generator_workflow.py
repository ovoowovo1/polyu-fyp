# -*- coding: utf-8 -*-
"""State helpers for generator node workflow."""

import uuid
from typing import Any, Dict, List

from app.agents.nodes.generator_config import SECTION_ORDER


def expected_question_counts(state: Dict[str, Any]) -> Dict[str, int]:
    question_types = state.get("question_types")
    if question_types:
        return {
            "multiple_choice": question_types.get("multiple_choice", 0),
            "short_answer": question_types.get("short_answer", 0),
            "essay": question_types.get("essay", 0),
        }
    return {
        "multiple_choice": state.get("num_questions", 10),
        "short_answer": 0,
        "essay": 0,
    }


def build_generated_questions(section_results: Dict[str, List[Dict[str, Any]]], build_question) -> list:
    questions = []
    for question_type in SECTION_ORDER:
        for raw_question in section_results[question_type]:
            questions.append(build_question(question_type, raw_question))
    return questions


def build_generator_result(state: Dict[str, Any], *, questions: list, exam_name: str) -> Dict[str, Any]:
    exam_id = state.get("exam_id") or f"exam_{uuid.uuid4().hex[:12]}"
    return {
        **state,
        "questions": questions,
        "exam_name": exam_name,
        "exam_id": exam_id,
        "feedback": "",
    }
