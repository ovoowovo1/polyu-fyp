from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from app.logger import get_logger
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


def _build_grading_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "marks_earned": {"type": "number"},
            "feedback": {"type": "string"},
            "is_correct": {"type": "boolean"},
            "analysis": {"type": "string"},
        },
        "required": ["marks_earned", "feedback", "is_correct", "analysis"],
    }


def _format_marking_criteria(marking_scheme: Optional[List[Dict[str, Any]]]) -> str:
    if not marking_scheme:
        return "No specific marking criteria provided. Use your knowledge to evaluate the answer."
    return "\n".join(
        f"- {item.get('criterion', 'Criterion')}: {item.get('marks', 0)} marks"
        for item in marking_scheme
    )


def _format_reference_answer(model_answer: Optional[str]) -> str:
    if model_answer:
        return f"Reference/Model Answer:\n{model_answer}"
    return "No model answer provided. Use your knowledge to evaluate correctness based on the question."


def _build_grade_answer_prompt(
    *,
    question_text: str,
    model_answer: Optional[str],
    marking_scheme: Optional[List[Dict[str, Any]]],
    student_answer: str,
    max_marks: int,
) -> str:
    return f"""
You are an objective and expert exam grader.

**Task**: Grade the student's answer based on the provided criteria.

**Question**: {question_text}
**Maximum Marks**: {max_marks}

**Marking Criteria**:
{_format_marking_criteria(marking_scheme)}

{_format_reference_answer(model_answer)}

**Student's Answer**:
{student_answer if student_answer else "(No answer provided)"}

**Grading Philosophy**:
1. **Prioritize Substance**: If the student's answer addresses the core requirements of the marking criteria, award full marks, even if they use different terminology or are very concise.
2. **Partial Credit**: Be generous with partial marks if a portion of the criteria is met.
3. **Reasoning First**: Analyze the answer against each criterion before deciding the final score.

**Instructions**:
- Provide feedback in 2-3 sentences max.
- Feedback should tell the student exactly what they missed (if any).
- Respond in English.

**Response Format**:
You MUST respond with valid JSON using this schema:
{{
  "analysis": "Step-by-step evaluation of the answer against the criteria",
  "marks_earned": <number>,
  "feedback": "Brief explanation",
  "is_correct": <boolean, true only if marks_earned == {max_marks}>
}}
"""


def _extract_grade_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))

        raw_match = re.search(r"\{[^{}]*\"marks_earned\"[^{}]*\}", text, re.DOTALL)
        if raw_match:
            return json.loads(raw_match.group(0))

        logger.error("[AI Grading] Could not parse JSON from response: %s", text)
        raise RuntimeError(f"Could not parse JSON from response: {text[:200]}")


def _clamp_marks(result: Dict[str, Any], max_marks: int) -> Dict[str, Any]:
    marks = result.get("marks_earned", 0)
    if marks < 0:
        result["marks_earned"] = 0
    elif marks > max_marks:
        result["marks_earned"] = max_marks
    return result


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

    async def _grade_answer(api_key: str, schema: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        system_prompt = (
            "You are a grading assistant. You MUST respond with valid JSON only, no markdown formatting.\n"
            f"The JSON must match this schema: {json.dumps(schema)}"
        )

        logger.info("[AI Grading] Calling model via OpenAI-compatible API: %s", model_name)
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                seed=0,
                response_format={"type": "json_object"},
            )
        )

        if hasattr(response, "choices") and response.choices:
            logger.info("[AI Grading] Choices: %s", len(response.choices))
            for index, choice in enumerate(response.choices):
                finish_reason = getattr(choice, "finish_reason", "N/A")
                logger.info("[AI Grading] Choice %s finish_reason: %s", index, finish_reason)
        else:
            logger.warning("[AI Grading] No choices in response")

        text = extract_chat_completion_text(response, operation_name)
        logger.info("[AI Grading] Response text preview: %s", text[:500] if text else "EMPTY/None")
        if not text:
            logger.error("[AI Grading] Full response object: %s", response)
            raise RuntimeError("Empty response from grading model")

        result = _extract_grade_json(text)
        logger.info("[AI Grading] Parsed result: %s", result)
        return _clamp_marks(result, max_marks)

    try:
        return await with_llm_retry_async(
            operation_name,
            _grade_answer,
            schema,
            prompt,
            error_type=RuntimeError,
        )
    except Exception as err:
        logger.error("AI grading failed: %s", err)
        return {
            "marks_earned": 0,
            "feedback": f"AI grading failed: {str(err)}. Please grade manually.",
            "is_correct": False,
        }


def _build_exam_overall_comment_prompt(submission_summary: str, total_score: int, total_marks: int) -> str:
    return f"""You are an encouraging teacher grading an exam.

Student's Total Score: {total_score} / {total_marks}

Question Performance Summary:
{submission_summary}

**Task**: Write an overall comment for this student (approx. 3-5 sentences).

**Structure**:
1. **Praise**: Start by explicitly praising what the student did well (e.g., "You demonstrated a strong understanding of...").
2. **Improvement**: Then, gently explain the main areas that need improvement based on their mistakes (e.g., "However, you should review...").
3. **Encouragement**: End with a professional and supportive closing.

**Tone**: Professional, supportive, constructive.
**Language**: English only.

Write the comment now."""


async def ai_generate_exam_overall_comment(
    submission_summary: str,
    total_score: int,
    total_marks: int,
    *,
    operation_name: str = "AI Exam Overall Comment",
) -> str:
    prompt = _build_exam_overall_comment_prompt(submission_summary, total_score, total_marks)

    async def _generate_comment(api_key: str, prompt: str) -> str:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are an encouraging teacher providing feedback on exam performance."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
        )
        text = extract_chat_completion_text(response, operation_name)
        if not text:
            raise RuntimeError("Empty response from model")
        return text

    try:
        return await with_llm_retry_async(
            operation_name,
            _generate_comment,
            prompt,
            error_type=RuntimeError,
        )
    except Exception as err:
        logger.error("AI overall comment failed: %s", err)
        return "AI comment generation failed."
