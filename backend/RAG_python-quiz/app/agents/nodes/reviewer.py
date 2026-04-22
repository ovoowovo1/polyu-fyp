# -*- coding: utf-8 -*-
"""
Reviewer node for generated exam questions.
"""

from typing import Any, Dict, List, Optional
import asyncio
import base64
import json
import os

from pydantic import BaseModel

from app.agents.schemas import ExamQuestion, ReviewIssue, ReviewResult
from app.logger import get_logger
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)

IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "static",
    "images",
)

MIN_PASS_SCORE = 70.0


class _ReviewIssue(BaseModel):
    question_id: str
    issue_type: str
    description: str
    suggestion: str


class _ReviewOutput(BaseModel):
    overall_score: float
    is_valid: bool
    decision: str
    research_goal: str = ""
    summary: str
    issues: List[_ReviewIssue]


REVIEWER_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["overall_score", "is_valid", "decision", "summary", "issues"],
    "properties": {
        "overall_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": "Overall quality score (0-100)",
        },
        "is_valid": {
            "type": "boolean",
            "description": "Whether the review is passed",
        },
        "decision": {
            "type": "string",
            "enum": ["PASS", "REWRITE", "RESEARCH"],
            "description": "Action to take after review",
        },
        "research_goal": {
            "type": "string",
            "description": "Specific topic to research when decision is RESEARCH",
        },
        "summary": {
            "type": "string",
            "description": "Review summary",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question_id", "issue_type", "description", "suggestion"],
                "properties": {
                    "question_id": {"type": "string"},
                    "issue_type": {
                        "type": "string",
                        "enum": ["context_mismatch", "answer_error", "marking_unclear", "image_issue"],
                    },
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "description": "List of issues found; empty when no problems were found",
        },
    },
    "additionalProperties": False,
}


def _format_marking_scheme(question: ExamQuestion) -> str:
    if not question.marking_scheme:
        return "N/A"

    parts = []
    for criterion in question.marking_scheme:
        explanation = ""
        if criterion.explanation and criterion.explanation != criterion.criterion:
            explanation = f" ({criterion.explanation})"
        parts.append(f"{criterion.criterion} [{criterion.marks} mark(s)]{explanation}")
    return "; ".join(parts)


def _build_review_prompt(
    context: str,
    questions: List[ExamQuestion],
    custom_prompt: str = "",
    has_images: bool = False,
) -> str:
    questions_text = ""
    for index, question in enumerate(questions, 1):
        if question.image_description:
            if question.image_path:
                image_info = (
                    f"Yes - Image Description: {question.image_description} "
                    "(Image attached below, please review together)"
                )
            else:
                image_info = f"Yes - {question.image_description} (Image generation failed)"
        else:
            image_info = "No"

        options_text = ", ".join(question.choices) if question.choices else "N/A"
        correct_answer_text = "N/A"
        if (
            question.choices
            and question.correct_answer_index is not None
            and 0 <= question.correct_answer_index < len(question.choices)
        ):
            correct_answer_text = question.choices[question.correct_answer_index]

        questions_text += f"""
### Question {index} (ID: {question.question_id})
- Question Type: {question.question_type}
- Bloom Level: {question.bloom_level}
- Marks: {question.marks}
- Question: {question.question_text}
- Options: {options_text}
- Correct Answer: {correct_answer_text}
- Reference Answer / Model Answer: {question.model_answer or 'N/A'}
- Marking Scheme / Rubric: {_format_marking_scheme(question)}
- Explanation: {question.rationale}
- Attached Image: {image_info}
"""

    image_review_note = ""
    if has_images:
        image_review_note = """
## Image Review Instructions
This review includes images. Check:
- whether the image matches the question description
- whether the image is clear and helpful
- whether the image style is suitable for educational use
"""

    custom_req_note = ""
    if custom_prompt:
        custom_req_note = f"""
## User Custom Requirements (CRITICAL)
The user explicitly requested: "{custom_prompt}"
You MUST check whether the generated questions meet these requirements.
- If a requested topic is missing, use decision "RESEARCH" and set `research_goal`.
- If a requested format or style is not followed, mention it in the issues.
"""

    return f"""You are a senior exam review expert. Review the following exam questions generated from the course material.

## Review Criteria
1. User requirements compliance
2. Content accuracy
3. Answer correctness
4. Question clarity
5. Bloom level appropriateness
6. Chart/image reasonableness
{image_review_note}
{custom_req_note}

## Course Material Summary
{context}...

## Questions to Review
{questions_text}

## Serious Errors
Mark `is_valid = false` if any of the following is true:
- the answer is obviously wrong
- the question is irrelevant to the course material
- multiple options could be correct in a multiple-choice question
- a short-answer or essay question is missing `model_answer`
- any question is missing a usable marking scheme / rubric

## Question-Type Guidance
- `multiple_choice` questions should include options and a single correct answer.
- `short_answer` and `essay` are valid open-response formats and should not be marked wrong just because they do not have options.
- Only use `marking_unclear` for `short_answer` or `essay` when `model_answer` or the marking scheme is missing, vague, or unusable.

## Decision Logic
- PASS: questions are good and valid
- REWRITE: questions are poor, but the course material is sufficient
- RESEARCH: the course material is missing key information; provide a concrete `research_goal`

## Output Format Requirements
Return valid JSON matching the schema.

Important reminders:
1. `issues` must be `[]` if no problems exist.
2. `overall_score` must be between 0 and 100.
3. Use `issue_type` from: context_mismatch, answer_error, marking_unclear, image_issue.
"""


def _load_image_as_base64(image_path: str) -> tuple[str, str]:
    with open(image_path, "rb") as file_obj:
        image_data = file_obj.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return mime_type, base64.b64encode(image_data).decode("utf-8")


def _get_absolute_image_path(relative_path: str) -> str:
    if relative_path.startswith("/static/images/"):
        filename = relative_path[len("/static/images/"):]
        return os.path.join(IMAGES_DIR, filename)
    return relative_path


def _strip_code_fences(raw_text: str) -> str:
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    elif cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    return cleaned_text.strip()


async def _run_review(
    api_key: str,
    prompt: str,
    model_name: str,
    image_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    client = get_llm_client(api_key)
    content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

    if image_paths:
        for image_path in image_paths:
            abs_path = _get_absolute_image_path(image_path)
            if not os.path.exists(abs_path):
                logger.warning("[Reviewer] Image not found: %s", abs_path)
                continue
            try:
                mime_type, b64_data = _load_image_as_base64(abs_path)
                content_list.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                    }
                )
            except Exception as exc:
                logger.warning("[Reviewer] Failed to load image %s: %s", abs_path, exc)

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": content_list}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "review_response",
                "strict": False,
                "schema": REVIEWER_OUTPUT_SCHEMA,
            },
        },
    )

    raw_text = extract_chat_completion_text(response, "憿撖拇")
    if not raw_text or not raw_text.strip():
        raise RuntimeError("API returned empty content during review")

    cleaned_text = _strip_code_fences(raw_text)
    try:
        result = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        start_idx = cleaned_text.find("{")
        end_idx = cleaned_text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                result = json.loads(cleaned_text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                logger.error("[Reviewer] JSON parse failed - raw preview: %s", raw_text[:300])
                raise RuntimeError(f"API returned unparseable review JSON: {exc}") from exc
        else:
            logger.error("[Reviewer] JSON parse failed - raw preview: %s", raw_text[:300])
            raise RuntimeError(f"API returned unparseable review JSON: {exc}") from exc

    if not isinstance(result, dict):
        raise RuntimeError("API returned review payload that is not a JSON object")
    return result


async def reviewer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    context = state.get("context", "")
    questions: List[ExamQuestion] = state.get("questions", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    warnings = state.get("warnings", [])

    logger.info("[Reviewer] 開始審核 - 題目數: %s, 目前重試: %s", len(questions), retry_count)

    if not questions:
        logger.warning("[Reviewer] No questions available for review")
        return {
            **state,
            "review_result": ReviewResult(
                is_valid=False,
                overall_score=0,
                issues=[],
                summary="No questions were generated for review.",
            ),
            "is_complete": True,
            "warnings": warnings + ["No questions were generated for review."],
        }

    model_name = get_default_llm_model_name()
    image_paths = [question.image_path for question in questions if question.image_path]
    has_images = bool(image_paths)
    if has_images:
        logger.info("[Reviewer] Including %s generated image(s) in review", len(image_paths))

    custom_prompt = state.get("custom_prompt", "")
    prompt = _build_review_prompt(
        context,
        questions,
        custom_prompt=custom_prompt,
        has_images=has_images,
    )

    try:
        result = await with_llm_retry_async(
            "憿撖拇",
            _run_review,
            prompt,
            model_name,
            image_paths if has_images else None,
            error_type=RuntimeError,
        )
    except Exception as exc:
        logger.error("[Reviewer] Review failed: %s", exc)
        return {
            **state,
            "review_result": ReviewResult(
                is_valid=True,
                overall_score=60,
                issues=[],
                summary=f"Review failed but generation was kept: {exc}",
            ),
            "is_complete": True,
            "warnings": warnings + [f"Review failed: {exc}"],
        }

    overall_score = result.get("overall_score", 0)
    is_valid = result.get("is_valid", False)
    decision = result.get("decision", "REWRITE")
    research_goal = result.get("research_goal", "")
    summary = result.get("summary", "")
    raw_issues = result.get("issues", [])

    issues = [
        ReviewIssue(
            question_id=issue.get("question_id", "unknown"),
            issue_type=issue.get("issue_type", "marking_unclear"),
            description=issue.get("description", ""),
            suggestion=issue.get("suggestion", ""),
        )
        for issue in raw_issues
    ]

    review_result = ReviewResult(
        is_valid=is_valid,
        overall_score=overall_score,
        issues=issues,
        summary=summary,
    )

    logger.info(
        "[Reviewer] 審核完成 - 分數: %s, 通過: %s, 決策: %s",
        overall_score,
        is_valid,
        decision,
    )
    logger.info("[Reviewer] 審核摘要: %s", summary)
    for index, issue in enumerate(issues, 1):
        logger.info(
            "  %s. [題目 %s] %s: %s (建議: %s)",
            index,
            issue.question_id,
            issue.issue_type,
            issue.description,
            issue.suggestion,
        )

    search_iterations = state.get("search_iterations", 0)
    max_search_iterations = state.get("max_search_iterations", 2)
    if decision == "RESEARCH" and research_goal:
        if search_iterations < max_search_iterations:
            logger.info(
                "[Reviewer] Need more research: %s (Iteration %s/%s)",
                research_goal,
                search_iterations + 1,
                max_search_iterations,
            )
            return {
                **state,
                "review_result": review_result,
                "feedback": summary,
                "research_goal": research_goal,
                "is_complete": False,
            }

        logger.warning(
            "[Reviewer] Research limit reached (%s); keeping current review result",
            max_search_iterations,
        )

    should_pass = (is_valid or overall_score >= MIN_PASS_SCORE) and decision != "REWRITE"
    if should_pass:
        logger.info("[Reviewer] Review passed")
        return {
            **state,
            "review_result": review_result,
            "is_complete": True,
            "warnings": warnings,
        }

    if retry_count >= max_retries:
        logger.warning("[Reviewer] Max retries reached (%s)", max_retries)
        return {
            **state,
            "review_result": review_result,
            "is_complete": True,
            "warnings": warnings + [
                f"The review failed (score: {overall_score}), but the maximum number of retries has been reached."
            ],
        }

    feedback_parts = [
        f"Review score: {overall_score}/100",
        f"Summary: {summary}",
        "Please regenerate the questions and address these issues:",
    ]
    for issue in issues:
        feedback_parts.append(
            f"- Question {issue.question_id}: {issue.description} | Suggestion: {issue.suggestion}"
        )
    feedback = "\n".join(feedback_parts)

    logger.info("[Reviewer] Sending rewrite feedback back to Generator")
    return {
        **state,
        "review_result": review_result,
        "feedback": feedback,
        "retry_count": retry_count + 1,
        "is_complete": False,
        "warnings": warnings,
    }
