# -*- coding: utf-8 -*-
"""Retry and provider fallback helpers for generator node."""

from app.agents.nodes.generator_config import SECTION_TO_ARRAY


def build_generation_retry_feedback(base_feedback: str, question_type: str, reason: str) -> str:
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


def should_fallback_to_non_strict_schema(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("strict" in message and "schema" in message)
        or ("json_schema" in message and ("unsupported" in message or "invalid" in message))
        or ("response_format" in message and ("unsupported" in message or "invalid" in message))
    )
