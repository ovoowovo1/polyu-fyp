# -*- coding: utf-8 -*-
"""LLM request helpers for generator sections."""

from typing import Any, Callable, Dict, Optional


async def request_section_generator_output(
    *,
    api_key: str,
    prompt: str,
    model_name: str,
    schema: Dict[str, Any],
    section_name: str,
    create_section_response: Callable,
    extract_text: Callable,
    should_fallback: Callable,
    logger,
) -> str:
    strict_modes = [True, False]
    last_error: Optional[Exception] = None

    for strict in strict_modes:
        try:
            response = await create_section_response(
                api_key=api_key,
                prompt=prompt,
                model_name=model_name,
                schema=schema,
                section_name=section_name,
                strict=strict,
            )
        except Exception as exc:
            last_error = exc
            if strict and should_fallback(exc):
                logger.warning(
                    "[Generator][%s] Provider rejected strict JSON schema; retrying with strict=False: %s",
                    section_name,
                    exc,
                )
                continue
            raise

        raw_text = extract_text(response, f"{section_name} question generation")
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
