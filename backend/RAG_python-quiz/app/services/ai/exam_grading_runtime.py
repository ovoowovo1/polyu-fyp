from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict


def extract_grade_json(text: str, *, logger) -> Dict[str, Any]:
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


def clamp_marks(result: Dict[str, Any], max_marks: int) -> Dict[str, Any]:
    marks = result.get("marks_earned", 0)
    if marks < 0:
        result["marks_earned"] = 0
    elif marks > max_marks:
        result["marks_earned"] = max_marks
    return result


def grading_fallback(error: Exception) -> Dict[str, Any]:
    return {
        "marks_earned": 0,
        "feedback": f"AI grading failed: {str(error)}. Please grade manually.",
        "is_correct": False,
    }


async def grade_answer_request(
    api_key: str,
    schema: Dict[str, Any],
    prompt: str,
    *,
    max_marks: int,
    operation_name: str,
    get_llm_client: Callable[[str], Any],
    get_default_llm_model_name: Callable[[], str],
    extract_chat_completion_text: Callable[[Any, str], str],
    extract_grade_json_func,
    to_thread,
    logger,
) -> Dict[str, Any]:
    client = get_llm_client(api_key)
    model_name = get_default_llm_model_name()
    system_prompt = (
        "You are a grading assistant. You MUST respond with valid JSON only, no markdown formatting.\n"
        f"The JSON must match this schema: {json.dumps(schema)}"
    )
    logger.info("[AI Grading] Calling model via OpenAI-compatible API: %s", model_name)
    response = await to_thread(
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

    result = extract_grade_json_func(text)
    logger.info("[AI Grading] Parsed result: %s", result)
    return clamp_marks(result, max_marks)


async def overall_comment_request(
    api_key: str,
    prompt: str,
    *,
    operation_name: str,
    get_llm_client: Callable[[str], Any],
    get_default_llm_model_name: Callable[[], str],
    extract_chat_completion_text: Callable[[Any, str], str],
    to_thread,
) -> str:
    client = get_llm_client(api_key)
    model_name = get_default_llm_model_name()
    response = await to_thread(
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
