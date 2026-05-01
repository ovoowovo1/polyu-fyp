# -*- coding: utf-8 -*-
"""
Generator node for exam question generation.
"""

from typing import Any, Dict, List, Optional
import asyncio
import uuid

from app.agents.nodes.generator_config import (
    BLOOM_DESCRIPTIONS,
    DEFAULT_MARKS,
    DIFFICULTY_TO_BLOOM,
    SECTION_CONFIG,
    SECTION_ORDER,
    SECTION_TO_ARRAY,
)
from app.agents.nodes.generator_payload import (
    GeneratorPayloadError,
    _build_json_error_context,
    _extract_outermost_json_object,
    _format_json_error_message,
    _normalize_generator_section_payload,
    _normalize_question_item,
    _parse_generator_payload,
    _strip_code_fences,
    _validate_marking_criteria,
)
from app.agents.nodes.generator_questions import (
    _build_exam_name,
    _build_exam_question,
    _build_marking_scheme,
    _distribute_marks,
)
from app.agents.nodes.generator_schema import (
    _build_generator_section_schema,
    _build_question_item_schema,
    _build_section_generator_prompt,
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
    array_name = SECTION_TO_ARRAY[question_type]
    retry_feedback = (
        f"Previous {question_type} generation returned an unusable payload.\n"
        f"Validation issue: {reason}\n"
        f"Regenerate ONLY `{array_name}` as one valid JSON object.\n"
        f"Do not include other top-level fields and do not continue the previous response.\n"
    )
    if base_feedback:
        return f"{base_feedback}\n\n{retry_feedback}"
    return retry_feedback


def _should_fallback_to_non_strict_schema(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("strict" in message and "schema" in message)
        or ("json_schema" in message and ("unsupported" in message or "invalid" in message))
        or ("response_format" in message and ("unsupported" in message or "invalid" in message))
    )


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
    strict_modes = [True, False]
    last_error: Optional[Exception] = None

    for strict in strict_modes:
        try:
            response = await _create_section_response(
                api_key=api_key,
                prompt=prompt,
                model_name=model_name,
                schema=schema,
                section_name=section_name,
                strict=strict,
            )
        except Exception as exc:
            last_error = exc
            if strict and _should_fallback_to_non_strict_schema(exc):
                logger.warning(
                    "[Generator][%s] Provider rejected strict JSON schema; retrying with strict=False: %s",
                    section_name,
                    exc,
                )
                continue
            raise

        raw_text = extract_chat_completion_text(response, f"{section_name} question generation")
        finish_reason = response.choices[0].finish_reason
        logger.debug("[Generator][%s] API finish_reason=%s strict=%s", section_name, finish_reason, strict)

        if finish_reason == "content_filter":
            raise RuntimeError(f"{section_name} generation was blocked by content filter")
        if finish_reason == "length":
            logger.warning("[Generator][%s] Response stopped because of length limit", section_name)
        if not raw_text or not raw_text.strip():
            raise RuntimeError(f"{section_name} generation returned empty content")
        return raw_text

    raise RuntimeError(f"{section_name} generation failed before receiving a response") from last_error  # pragma: no cover


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
    section_name = question_type
    schema = _build_generator_section_schema(question_type, count)
    prompt = _build_section_generator_prompt(
        context=context,
        difficulty=difficulty,
        topic=topic,
        question_type=question_type,
        count=count,
        feedback=base_feedback,
        custom_prompt=custom_prompt,
    )

    for attempt in range(max_generation_attempts):
        raw_text = await with_llm_retry_async(
            f"question_generation:{section_name}",
            _request_section_generator_output,
            prompt,
            model_name,
            schema,
            section_name,
            error_type=RuntimeError,
        )

        try:
            payload = _parse_generator_payload(raw_text)
            normalized_items = _normalize_generator_section_payload(
                payload,
                question_type=question_type,
                expected_count=count,
            )
            logger.info(
                "[Generator][%s] Section validation passed (attempt %s/%s)",
                section_name,
                attempt + 1,
                max_generation_attempts,
            )
            return normalized_items
        except GeneratorPayloadError as exc:
            logger.warning(
                "[Generator][%s] Section payload invalid (attempt %s/%s): %s",
                section_name,
                attempt + 1,
                max_generation_attempts,
                exc,
            )
            if exc.error_context:
                logger.error("[Generator][%s] JSON error context: %s", section_name, exc.error_context)
            logger.error("[Generator][%s] Full invalid payload:\n%s", section_name, exc.raw_text or raw_text)

            if attempt >= max_generation_attempts - 1:
                raise RuntimeError(
                    f"Generator section '{section_name}' generation parse/validation failure after "
                    f"{max_generation_attempts} attempts: {exc}"
                ) from exc

            prompt = _build_section_generator_prompt(
                context=context,
                difficulty=difficulty,
                topic=topic,
                question_type=question_type,
                count=count,
                feedback=_build_generation_retry_feedback(base_feedback, question_type, str(exc)),
                custom_prompt=custom_prompt,
            )

    raise RuntimeError(f"Generator section '{section_name}' failed without returning a validated payload")


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

    if question_types:
        expected_counts = {
            "multiple_choice": question_types.get("multiple_choice", 0),
            "short_answer": question_types.get("short_answer", 0),
            "essay": question_types.get("essay", 0),
        }
    else:
        expected_counts = {
            "multiple_choice": num_questions,
            "short_answer": 0,
            "essay": 0,
        }

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

    questions: List[ExamQuestion] = []
    for question_type in SECTION_ORDER:
        for raw_question in section_results[question_type]:
            questions.append(_build_exam_question(question_type, raw_question))

    logger.info(
        "[Generator] Generation complete - exam_name=%s total_questions=%s (MC=%s SA=%s Essay=%s)",
        exam_name,
        len(questions),
        len(section_results["multiple_choice"]),
        len(section_results["short_answer"]),
        len(section_results["essay"]),
    )

    exam_id = state.get("exam_id") or f"exam_{uuid.uuid4().hex[:12]}"
    return {
        **state,
        "questions": questions,
        "exam_name": exam_name,
        "exam_id": exam_id,
        "feedback": "",
    }
