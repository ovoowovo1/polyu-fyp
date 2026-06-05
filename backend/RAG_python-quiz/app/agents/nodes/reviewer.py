# -*- coding: utf-8 -*-
"""Reviewer node for generated exam questions."""

from typing import Any, Dict, List, Optional
import asyncio
import os

from app.agents.nodes.review_decision import build_review_result, build_rewrite_feedback
from app.agents.nodes.review_media import (
    get_absolute_image_path as _media_get_absolute_image_path,
    load_image_as_base64 as _media_load_image_as_base64,
)
from app.agents.nodes.review_prompt import (
    build_review_prompt as _prompt_build_review_prompt,
    format_marking_scheme as _prompt_format_marking_scheme,
)
from app.agents.nodes.review_runtime import run_review_request
from app.agents.nodes.review_schema import (
    REVIEWER_OUTPUT_SCHEMA,
    ReviewIssuePayload as _ReviewIssue,
    ReviewOutputPayload as _ReviewOutput,
)
from app.agents.nodes.text_utils import strip_code_fences as _strip_code_fences
from app.agents.schemas import ExamQuestion, ReviewResult
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


def _format_marking_scheme(question: ExamQuestion) -> str:
    return _prompt_format_marking_scheme(question)


def _build_review_prompt(
    context: str,
    questions: List[ExamQuestion],
    custom_prompt: str = "",
    has_images: bool = False,
) -> str:
    return _prompt_build_review_prompt(context, questions, custom_prompt, has_images)


def _load_image_as_base64(image_path: str) -> tuple[str, str]:
    return _media_load_image_as_base64(image_path)


def _get_absolute_image_path(relative_path: str) -> str:
    return _media_get_absolute_image_path(relative_path, IMAGES_DIR)


async def _run_review(
    api_key: str,
    prompt: str,
    model_name: str,
    image_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return await run_review_request(
        api_key,
        prompt,
        model_name,
        image_paths,
        schema=REVIEWER_OUTPUT_SCHEMA,
        get_llm_client=get_llm_client,
        extract_text=extract_chat_completion_text,
        to_thread=asyncio.to_thread,
        get_absolute_image_path=_get_absolute_image_path,
        load_image_as_base64=_load_image_as_base64,
        logger=logger,
    )


def _empty_review_state(state: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
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


def _failed_review_state(state: Dict[str, Any], warnings: List[str], exc: Exception) -> Dict[str, Any]:
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


async def reviewer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    context = state.get("context", "")
    questions: List[ExamQuestion] = state.get("questions", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    warnings = state.get("warnings", [])

    logger.info("[Reviewer] Reviewing %s question(s), retry count: %s", len(questions), retry_count)
    if not questions:
        logger.warning("[Reviewer] No questions available for review")
        return _empty_review_state(state, warnings)

    model_name = get_default_llm_model_name()
    image_paths = [question.image_path for question in questions if question.image_path]
    has_images = bool(image_paths)
    if has_images:
        logger.info("[Reviewer] Including %s generated image(s) in review", len(image_paths))

    prompt = _build_review_prompt(
        context,
        questions,
        custom_prompt=state.get("custom_prompt", ""),
        has_images=has_images,
    )
    try:
        result = await with_llm_retry_async(
            "exam review",
            _run_review,
            prompt,
            model_name,
            image_paths if has_images else None,
            error_type=RuntimeError,
        )
    except Exception as exc:
        logger.error("[Reviewer] Review failed: %s", exc)
        return _failed_review_state(state, warnings, exc)

    review_result, decision_data, issues = build_review_result(result)
    overall_score = decision_data["overall_score"]
    is_valid = decision_data["is_valid"]
    decision = decision_data["decision"]
    research_goal = decision_data["research_goal"]
    summary = decision_data["summary"]

    logger.info(
        "[Reviewer] Review completed - score=%s valid=%s decision=%s",
        overall_score,
        is_valid,
        decision,
    )
    logger.info("[Reviewer] Review summary: %s", summary)
    for index, issue in enumerate(issues, 1):
        logger.info(
            "[Reviewer] Issue %s question=%s type=%s description=%s suggestion=%s",
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
        logger.warning("[Reviewer] Research limit reached (%s); keeping current review result", max_search_iterations)

    should_pass = (is_valid or overall_score >= MIN_PASS_SCORE) and decision != "REWRITE"
    if should_pass:
        logger.info("[Reviewer] Review passed")
        return {**state, "review_result": review_result, "is_complete": True, "warnings": warnings}

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

    logger.info("[Reviewer] Sending rewrite feedback back to Generator")
    return {
        **state,
        "review_result": review_result,
        "feedback": build_rewrite_feedback(overall_score, summary, issues),
        "retry_count": retry_count + 1,
        "is_complete": False,
        "warnings": warnings,
    }
