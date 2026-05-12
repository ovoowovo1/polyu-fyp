from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

from app.logger import get_logger
from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


def _parse_structured_json_text(text: str, operation_name: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"{operation_name} returned invalid JSON: {raw[:200]}") from err

    if not isinstance(parsed, dict):
        raise RuntimeError(f"{operation_name} returned JSON that is not an object")
    return parsed


def _validate_structured_json_result(
    result: Dict[str, Any],
    schema: Dict[str, Any],
    operation_name: str,
) -> None:
    missing = [field for field in schema.get("required", []) if field not in result]
    if missing:
        raise RuntimeError(f"{operation_name} returned JSON missing required fields: {missing}")


def _prefers_plain_json_response(model_name: str) -> bool:
    return (model_name or "").lower().startswith("deepseek/")


def _plain_json_system_prompt(schema: Dict[str, Any], system_prompt: Optional[str]) -> str:
    prefix = f"{system_prompt.strip()}\n\n" if system_prompt else ""
    return (
        f"{prefix}Return only valid JSON matching this schema. "
        "Do not include markdown, comments, or extra text.\n"
        f"Schema:\n{json.dumps(schema)}"
    )


def _build_json_schema_kwargs(
    *,
    model_name: str,
    prompt: str,
    schema: Dict[str, Any],
    system_prompt: Optional[str],
    temperature: float,
) -> Dict[str, Any]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": False,
                "schema": schema,
            },
        },
    }


def _build_plain_json_kwargs(
    *,
    model_name: str,
    prompt: str,
    schema: Dict[str, Any],
    system_prompt: Optional[str],
    temperature: float,
) -> Dict[str, Any]:
    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _plain_json_system_prompt(schema, system_prompt)},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }


async def generate_structured_json(
    prompt: str,
    schema: Dict[str, Any],
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    async def _generate(api_key: str) -> Dict[str, Any]:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()

        async def _call_model(*, response_format_mode: str, fallback_mode: str) -> Dict[str, Any]:
            if response_format_mode == "plain_json":
                kwargs = _build_plain_json_kwargs(
                    model_name=model_name,
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )
            else:
                kwargs = _build_json_schema_kwargs(
                    model_name=model_name,
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )

            logger.info(
                "[%s] structured_json request model=%s response_format_mode=%s fallback_mode=%s",
                operation_name,
                model_name,
                response_format_mode,
                fallback_mode,
            )
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
            text = extract_chat_completion_text(response, operation_name)
            if not text:
                raise RuntimeError(f"{operation_name} returned empty content")
            result = _parse_structured_json_text(text, operation_name)
            _validate_structured_json_result(result, schema, operation_name)
            return result

        if _prefers_plain_json_response(model_name):
            try:
                return await _call_model(response_format_mode="plain_json", fallback_mode="preferred")
            except Exception as err:
                logger.error(
                    "[%s] structured_json plain JSON request failed model=%s: %s",
                    operation_name,
                    model_name,
                    err,
                )
                raise

        try:
            return await _call_model(response_format_mode="json_schema", fallback_mode="available")
        except Exception as first_err:
            logger.warning(
                "[%s] structured_json json_schema request failed model=%s; retrying once with plain JSON fallback: %s",
                operation_name,
                model_name,
                first_err,
            )
            try:
                return await _call_model(
                    response_format_mode="plain_json",
                    fallback_mode="retry_after_json_schema_failure",
                )
            except Exception as fallback_err:
                logger.error(
                    "[%s] structured_json plain JSON fallback failed model=%s after json_schema error=%s fallback_error=%s",
                    operation_name,
                    model_name,
                    first_err,
                    fallback_err,
                )
                raise RuntimeError(
                    f"{operation_name} failed after plain JSON fallback: {fallback_err}"
                ) from fallback_err

    return await with_llm_retry_async(
        operation_name,
        _generate,
        error_type=RuntimeError,
    )
