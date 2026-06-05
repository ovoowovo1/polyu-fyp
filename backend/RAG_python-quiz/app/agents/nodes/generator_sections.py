# -*- coding: utf-8 -*-
"""Section validation workflow for generator node."""

from typing import Any, Callable, Dict, List

from app.agents.nodes.generator_payload import GeneratorPayloadError


async def generate_question_section(
    *,
    context: str,
    difficulty: str,
    topic: str,
    question_type: str,
    count: int,
    base_feedback: str,
    custom_prompt: str,
    model_name: str,
    max_generation_attempts: int,
    build_schema: Callable,
    build_prompt: Callable,
    retry_async: Callable,
    request_output: Callable,
    parse_payload: Callable,
    normalize_payload: Callable,
    build_retry_feedback: Callable,
    logger,
) -> List[Dict[str, Any]]:
    section_name = question_type
    schema = build_schema(question_type, count)
    prompt = build_prompt(
        context=context,
        difficulty=difficulty,
        topic=topic,
        question_type=question_type,
        count=count,
        feedback=base_feedback,
        custom_prompt=custom_prompt,
    )

    for attempt in range(max_generation_attempts):
        raw_text = await retry_async(
            f"question_generation:{section_name}",
            request_output,
            prompt,
            model_name,
            schema,
            section_name,
            error_type=RuntimeError,
        )

        try:
            payload = parse_payload(raw_text)
            normalized_items = normalize_payload(
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

            prompt = build_prompt(
                context=context,
                difficulty=difficulty,
                topic=topic,
                question_type=question_type,
                count=count,
                feedback=build_retry_feedback(base_feedback, question_type, str(exc)),
                custom_prompt=custom_prompt,
            )

    raise RuntimeError(f"Generator section '{section_name}' failed without returning a validated payload")
