"""Backward-compatible public AI service API.

This module intentionally stays small. Existing imports should continue to work:

    from app.services.ai_service import generate_structured_json
    from app.services.ai_service import ai_grade_answer

Implementation now lives in focused modules under `app.services.llm`,
`app.services.quiz_feedback_service`, and `app.services.exam_ai_grading_service`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.services import exam_ai_grading_service as _exam_ai_grading_service
from app.services import quiz_feedback_service as _quiz_feedback_service
from app.services.llm import structured_json as _structured_json
from app.services.llm import text_completion as _text_completion
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text


def _sync_dependency_overrides() -> None:
    """Keep old test/mock paths working during the refactor.

    Existing tests patch symbols on `app.services.ai_service`. The implementation has moved
    to smaller modules, so this function propagates patched facade dependencies into the
    implementation modules before each public call.
    """
    for module in (_structured_json, _text_completion, _quiz_feedback_service, _exam_ai_grading_service):
        module.get_llm_client = get_llm_client
        module.get_default_llm_model_name = get_default_llm_model_name
        module.with_llm_retry_async = with_llm_retry_async
        module.extract_chat_completion_text = extract_chat_completion_text

    # Backward compatibility for tests that patch app.services.ai_service.get_settings.
    # The new quiz feedback implementation does not need get_settings, but keeping this
    # exported symbol avoids accidental AttributeError in older tests.
    globals()["get_settings"] = get_settings


async def generate_structured_json(
    prompt: str,
    schema: Dict[str, Any],
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    _sync_dependency_overrides()
    return await _structured_json.generate_structured_json(
        prompt,
        schema,
        operation_name=operation_name,
        system_prompt=system_prompt,
        temperature=temperature,
    )


async def generate_text_completion(
    prompt: str,
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> str:
    _sync_dependency_overrides()
    return await _text_completion.generate_text_completion(
        prompt,
        operation_name=operation_name,
        system_prompt=system_prompt,
        temperature=temperature,
    )


async def generate_quiz_feedback_text(
    quiz_name: str,
    score: int,
    total: int,
    percentage: int,
    bloom_summary: List[Dict[str, Any]],
    questions: List[Dict[str, Any]],
    *,
    operation_name: str = "AI 測驗回饋生成",
) -> str:
    _sync_dependency_overrides()
    return await _quiz_feedback_service.generate_quiz_feedback_text(
        quiz_name,
        score,
        total,
        percentage,
        bloom_summary,
        questions,
        operation_name=operation_name,
    )


async def ai_grade_answer(
    question_text: str,
    question_type: str,
    model_answer: Optional[str],
    marking_scheme: Optional[List[Dict[str, Any]]],
    student_answer: str,
    max_marks: int,
    *,
    operation_name: str = "AI Exam Grading",
) -> Dict[str, Any]:
    _sync_dependency_overrides()
    return await _exam_ai_grading_service.ai_grade_answer(
        question_text=question_text,
        question_type=question_type,
        model_answer=model_answer,
        marking_scheme=marking_scheme,
        student_answer=student_answer,
        max_marks=max_marks,
        operation_name=operation_name,
    )


async def ai_generate_exam_overall_comment(
    submission_summary: str,
    total_score: int,
    total_marks: int,
    *,
    operation_name: str = "AI Exam Overall Comment",
) -> str:
    _sync_dependency_overrides()
    return await _exam_ai_grading_service.ai_generate_exam_overall_comment(
        submission_summary,
        total_score,
        total_marks,
        operation_name=operation_name,
    )


__all__ = [
    "generate_structured_json",
    "generate_text_completion",
    "generate_quiz_feedback_text",
    "ai_grade_answer",
    "ai_generate_exam_overall_comment",
]
