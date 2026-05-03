"""Backward-compatible public AI service API.

This module intentionally stays small. Existing imports continue to work:

    from app.services.ai_service import generate_structured_json
    from app.services.ai_service import ai_grade_answer

Implementation lives in focused modules under ``app.services.llm``,
``app.services.quiz_feedback_service``, and ``app.services.exam_ai_grading_service``.
"""

from __future__ import annotations

from app.services.exam_ai_grading_service import (
    ai_generate_exam_overall_comment,
    ai_grade_answer,
)
from app.services.llm.structured_json import generate_structured_json
from app.services.llm.text_completion import generate_text_completion
from app.services.quiz_feedback_service import generate_quiz_feedback_text

__all__ = [
    "generate_structured_json",
    "generate_text_completion",
    "generate_quiz_feedback_text",
    "ai_grade_answer",
    "ai_generate_exam_overall_comment",
]
