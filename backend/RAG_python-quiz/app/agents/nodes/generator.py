# -*- coding: utf-8 -*-
"""Generator node facade for exam question generation."""

from typing import Any, Dict, List, Optional
import asyncio

from app.agents.nodes.generator_config import (
    BLOOM_DESCRIPTIONS,
    DIFFICULTY_TO_BLOOM,
    SECTION_CONFIG,
    SECTION_ORDER,
    SECTION_TO_ARRAY,
)
from app.agents.nodes.generator_payload import (
    _normalize_generator_section_payload,
    _parse_generator_payload,
)
from app.agents.nodes.generator_questions import (
    _build_exam_name,
    _build_exam_question,
    _build_marking_scheme,
    _distribute_marks,
)
from app.agents.nodes.generator_retry import (
    build_generation_retry_feedback,
    should_fallback_to_non_strict_schema,
)
from app.agents.nodes.generator_runtime import request_section_generator_output
from app.agents.nodes.generator_schema import (
    _build_generator_section_schema,
    _build_question_item_schema,
    _build_section_generator_prompt,
)
from app.agents.nodes.generator_sections import generate_question_section
from app.agents.nodes.generator_workflow import (
    build_generated_questions,
    build_generator_result,
    expected_question_counts,
)
from app.logger import get_logger
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


def _build_generation_retry_feedback(base_feedback: str, question_type: str, reason: str) -> str:
    return build_generation_retry_feedback(base_feedback, question_type, reason)


def _should_fallback_to_non_strict_schema(exc: Exception) -> bool:
    return should_fallback_to_non_strict_schema(exc)


async def _create_section_response(
    *,
    api_key: str,
    prompt: str,
    model_name: str,
    schema: Dict[str, Any],
    section_name: str,
    strict: bool,
):
    client = get_llm_client(api_key)
    return await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": f"{section_name}_generation_response",
                "strict": strict,
                "schema": schema,
            },
        },
    )


async def _request_section_generator_output(
    api_key: str,
    prompt: str,
    model_name: str,
    schema: Dict[str, Any],
    section_name: str,
) -> str:
    return await request_section_generator_output(
        api_key=api_key,
        prompt=prompt,
        model_name=model_name,
        schema=schema,
        section_name=section_name,
        create_section_response=_create_section_response,
        extract_text=extract_chat_completion_text,
        should_fallback=_should_fallback_to_non_strict_schema,
        logger=logger,
    )


async def _generate_question_section(
    *,
    context: str,
    difficulty: str,
    topic: str,
    question_type: str,
    count: int,
    base_feedback: str,
    custom_prompt: str,
    model_name: str,
    max_generation_attempts: int = 3,
) -> List[Dict[str, Any]]:
    return await generate_question_section(
        context=context,
        difficulty=difficulty,
        topic=topic,
        question_type=question_type,
        count=count,
        base_feedback=base_feedback,
        custom_prompt=custom_prompt,
        model_name=model_name,
        max_generation_attempts=max_generation_attempts,
        build_schema=_build_generator_section_schema,
        build_prompt=_build_section_generator_prompt,
        retry_async=with_llm_retry_async,
        request_output=_request_section_generator_output,
        parse_payload=_parse_generator_payload,
        normalize_payload=_normalize_generator_section_payload,
        build_retry_feedback=_build_generation_retry_feedback,
        logger=logger,
    )


async def generator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    context = state.get("context", "")
    num_questions = state.get("num_questions", 10)
    question_types = state.get("question_types")
    custom_prompt = state.get("custom_prompt", "")
    difficulty = state.get("difficulty", "medium")
    topic = state.get("topic", "")
    base_feedback = state.get("feedback", "")
    retry_count = state.get("retry_count", 0)

    if question_types:
        logger.info(
            "[Generator] Start generation - question_types=%s difficulty=%s retry=%s",
            question_types,
            difficulty,
            retry_count,
        )
    else:
        logger.info(
            "[Generator] Start generation - num_questions=%s difficulty=%s retry=%s",
            num_questions,
            difficulty,
            retry_count,
        )

    if custom_prompt:
        logger.info("[Generator] Custom prompt preview: %s...", custom_prompt[:100])

    if not context:
        raise ValueError("Missing context for question generation")

    expected_counts = expected_question_counts(state)
    model_name = get_default_llm_model_name()
    section_results: Dict[str, List[Dict[str, Any]]] = {
        "multiple_choice": [],
        "short_answer": [],
        "essay": [],
    }

    for question_type in SECTION_ORDER:
        count = expected_counts[question_type]
        if count <= 0:
            continue

        logger.info(
            "[Generator][%s] Generating section with count=%s using model=%s",
            question_type,
            count,
            model_name,
        )
        section_results[question_type] = await _generate_question_section(
            context=context,
            difficulty=difficulty,
            topic=topic,
            question_type=question_type,
            count=count,
            base_feedback=base_feedback,
            custom_prompt=custom_prompt,
            model_name=model_name,
        )

    exam_name = _build_exam_name(state, topic)
    questions = build_generated_questions(section_results, _build_exam_question)

    logger.info(
        "[Generator] Generation complete - exam_name=%s total_questions=%s (MC=%s SA=%s Essay=%s)",
        exam_name,
        len(questions),
        len(section_results["multiple_choice"]),
        len(section_results["short_answer"]),
        len(section_results["essay"]),
    )
    return build_generator_result(state, questions=questions, exam_name=exam_name)
