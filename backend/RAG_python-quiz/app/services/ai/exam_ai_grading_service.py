from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.logger import get_logger
from app.services.ai import exam_grading_prompts, exam_grading_runtime
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


def _build_grading_schema() -> Dict[str, Any]:
    return exam_grading_prompts.build_grading_schema()


def _format_marking_criteria(marking_scheme: Optional[List[Dict[str, Any]]]) -> str:
    return exam_grading_prompts.format_marking_criteria(marking_scheme)


def _format_reference_answer(model_answer: Optional[str]) -> str:
    return exam_grading_prompts.format_reference_answer(model_answer)


def _build_grade_answer_prompt(
    *,
    question_text: str,
    model_answer: Optional[str],
    marking_scheme: Optional[List[Dict[str, Any]]],
    student_answer: str,
    max_marks: int,
) -> str:
    return exam_grading_prompts.build_grade_answer_prompt(
        question_text=question_text,
        model_answer=model_answer,
        marking_scheme=marking_scheme,
        student_answer=student_answer,
        max_marks=max_marks,
    )


def _extract_grade_json(text: str) -> Dict[str, Any]:
    return exam_grading_runtime.extract_grade_json(text, logger=logger)


def _clamp_marks(result: Dict[str, Any], max_marks: int) -> Dict[str, Any]:
    return exam_grading_runtime.clamp_marks(result, max_marks)


async def _grade_answer(api_key: str, schema: Dict[str, Any], prompt: str, max_marks: int, operation_name: str):
    return await exam_grading_runtime.grade_answer_request(
        api_key,
        schema,
        prompt,
        max_marks=max_marks,
        operation_name=operation_name,
        get_llm_client=get_llm_client,
        get_default_llm_model_name=get_default_llm_model_name,
        extract_chat_completion_text=extract_chat_completion_text,
        extract_grade_json_func=_extract_grade_json,
        to_thread=asyncio.to_thread,
        logger=logger,
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
    schema = _build_grading_schema()
    prompt = _build_grade_answer_prompt(
        question_text=question_text,
        model_answer=model_answer,
        marking_scheme=marking_scheme,
        student_answer=student_answer,
        max_marks=max_marks,
    )
    logger.info("[AI Grading] question_type=%s max_marks=%s prompt_length=%s", question_type, max_marks, len(prompt))

    try:
        return await with_llm_retry_async(
            operation_name,
            _grade_answer,
            schema,
            prompt,
            max_marks,
            operation_name,
            error_type=RuntimeError,
        )
    except Exception as err:
        logger.error("AI grading failed: %s", err)
        return exam_grading_runtime.grading_fallback(err)


def _build_exam_overall_comment_prompt(submission_summary: str, total_score: int, total_marks: int) -> str:
    return exam_grading_prompts.build_exam_overall_comment_prompt(submission_summary, total_score, total_marks)


async def _generate_comment(api_key: str, prompt: str, operation_name: str) -> str:
    return await exam_grading_runtime.overall_comment_request(
        api_key,
        prompt,
        operation_name=operation_name,
        get_llm_client=get_llm_client,
        get_default_llm_model_name=get_default_llm_model_name,
        extract_chat_completion_text=extract_chat_completion_text,
        to_thread=asyncio.to_thread,
    )


async def ai_generate_exam_overall_comment(
    submission_summary: str,
    total_score: int,
    total_marks: int,
    *,
    operation_name: str = "AI Exam Overall Comment",
) -> str:
    prompt = _build_exam_overall_comment_prompt(submission_summary, total_score, total_marks)
    try:
        return await with_llm_retry_async(
            operation_name,
            _generate_comment,
            prompt,
            operation_name,
            error_type=RuntimeError,
        )
    except Exception as err:
        logger.error("AI overall comment failed: %s", err)
        return "AI comment generation failed."
