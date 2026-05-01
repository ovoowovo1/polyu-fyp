from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.agents.nodes.generator_config import DEFAULT_MARKS, SECTION_TO_ARRAY


class GeneratorPayloadError(RuntimeError):
    """Raised when the model output is not a usable exam payload."""

    def __init__(
        self,
        message: str,
        *,
        raw_text: Optional[str] = None,
        error_context: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.error_context = error_context


def _strip_code_fences(raw_text: str) -> str:
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    elif cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    return cleaned_text.strip()


def _extract_outermost_json_object(text: str) -> Optional[str]:
    start_idx = text.find("{")
    if start_idx == -1:
        return None

    brace_count = 0
    end_idx = -1
    in_string = False
    escape_next = False

    for index in range(start_idx, len(text)):
        char = text[index]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end_idx = index
                break

    if end_idx == -1:
        return None
    return text[start_idx:end_idx + 1]


def _build_json_error_context(raw_text: str, position: int, window: int = 120) -> str:
    start_idx = max(0, position - window)
    end_idx = min(len(raw_text), position + window)
    snippet = raw_text[start_idx:end_idx].replace("\n", "\\n")
    return f"char_window[{start_idx}:{end_idx}]={snippet}"


def _format_json_error_message(exc: json.JSONDecodeError) -> str:
    return (
        f"invalid JSON payload at line {exc.lineno} column {exc.colno} "
        f"(char {exc.pos}): {exc.msg}"
    )


def _parse_generator_payload(raw_text: str) -> Dict[str, Any]:
    if not raw_text or not raw_text.strip():
        raise GeneratorPayloadError(
            "generation parse/validation failure: API returned empty content",
            raw_text=raw_text,
        )

    cleaned_text = _strip_code_fences(raw_text)
    try:
        payload = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        extracted = _extract_outermost_json_object(cleaned_text)
        if extracted:
            try:
                payload = json.loads(extracted)
            except json.JSONDecodeError as extracted_exc:
                raise GeneratorPayloadError(
                    f"generation parse/validation failure: {_format_json_error_message(extracted_exc)}",
                    raw_text=raw_text,
                    error_context=_build_json_error_context(cleaned_text, extracted_exc.pos),
                ) from extracted_exc
        else:
            raise GeneratorPayloadError(
                f"generation parse/validation failure: {_format_json_error_message(exc)}",
                raw_text=raw_text,
                error_context=_build_json_error_context(cleaned_text, exc.pos),
            ) from exc

    if not isinstance(payload, dict):
        raise GeneratorPayloadError(
            "generation parse/validation failure: top-level payload must be a JSON object",
            raw_text=raw_text,
        )
    return payload


def _validate_marking_criteria(
    marking_criteria: Any,
    *,
    array_name: str,
    question_index: int,
) -> List[Any]:
    if not isinstance(marking_criteria, list) or not marking_criteria:
        raise GeneratorPayloadError(
            f"generation parse/validation failure: {array_name}[{question_index}].marking_criteria must be a non-empty list"
        )

    for criterion_index, criterion in enumerate(marking_criteria):
        if isinstance(criterion, str):
            if criterion.strip():
                continue
        elif isinstance(criterion, dict):
            if any(
                isinstance(criterion.get(key), str) and criterion.get(key).strip()
                for key in ("criterion", "explanation")
            ):
                continue

        raise GeneratorPayloadError(
            f"generation parse/validation failure: {array_name}[{question_index}].marking_criteria[{criterion_index}] must be a non-empty string or object"
        )
    return marking_criteria


def _normalize_question_item(
    item: Any,
    *,
    array_name: str,
    question_type: str,
    question_index: int,
) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise GeneratorPayloadError(
            f"generation parse/validation failure: {array_name}[{question_index}] must be a JSON object, got {type(item).__name__}"
        )

    normalized = dict(item)
    actual_type = normalized.get("question_type")
    if actual_type is None:
        normalized["question_type"] = question_type
    elif actual_type != question_type:
        raise GeneratorPayloadError(
            f"generation parse/validation failure: {array_name}[{question_index}].question_type must be '{question_type}'"
        )

    for required_field in ("bloom_level", "question_text", "rationale"):
        value = normalized.get(required_field)
        if not isinstance(value, str) or not value.strip():
            raise GeneratorPayloadError(
                f"generation parse/validation failure: {array_name}[{question_index}].{required_field} must be a non-empty string"
            )

    if question_type == "multiple_choice":
        normalized["marking_criteria"] = []
        choices = normalized.get("choices")
        if not isinstance(choices, list) or len(choices) != 4 or any(
            not isinstance(choice, str) or not choice.strip() for choice in choices
        ):
            raise GeneratorPayloadError(
                f"generation parse/validation failure: {array_name}[{question_index}].choices must contain exactly 4 non-empty strings"
            )
        answer_index = normalized.get("correct_answer_index")
        if not isinstance(answer_index, int) or not 0 <= answer_index <= 3:
            raise GeneratorPayloadError(
                f"generation parse/validation failure: {array_name}[{question_index}].correct_answer_index must be an integer from 0 to 3"
            )
    else:
        normalized["marking_criteria"] = _validate_marking_criteria(
            normalized.get("marking_criteria"),
            array_name=array_name,
            question_index=question_index,
        )
        model_answer = normalized.get("model_answer")
        if not isinstance(model_answer, str) or not model_answer.strip():
            raise GeneratorPayloadError(
                f"generation parse/validation failure: {array_name}[{question_index}].model_answer must be a non-empty string"
            )

    normalized["marks"] = DEFAULT_MARKS[question_type]

    image_description = normalized.get("image_description")
    if image_description is not None and not isinstance(image_description, str):
        raise GeneratorPayloadError(
            f"generation parse/validation failure: {array_name}[{question_index}].image_description must be a string or null"
        )

    return normalized


def _normalize_generator_section_payload(
    payload: Dict[str, Any],
    *,
    question_type: str,
    expected_count: int,
) -> List[Dict[str, Any]]:
    array_name = SECTION_TO_ARRAY[question_type]
    items = payload.get(array_name)
    if items is None and "questions" in payload:
        items = payload.get("questions")

    if items is None:
        raise GeneratorPayloadError(
            f"generation parse/validation failure: missing top-level field `{array_name}`"
        )
    if not isinstance(items, list):
        raise GeneratorPayloadError(
            f"generation parse/validation failure: `{array_name}` must be a list"
        )

    normalized_items = [
        _normalize_question_item(
            item,
            array_name=array_name,
            question_type=question_type,
            question_index=index,
        )
        for index, item in enumerate(items)
    ]

    if len(normalized_items) != expected_count:
        raise GeneratorPayloadError(
            f"generation parse/validation failure: {question_type} count mismatch ({len(normalized_items)}/{expected_count})"
        )
    return normalized_items
