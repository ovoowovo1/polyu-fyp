# -*- coding: utf-8 -*-
"""
Generator node for exam question generation.
"""

from typing import Any, Dict, List, Optional
import asyncio
import json
import uuid

from app.agents.schemas import BloomLevel, ExamQuestion, MarkingCriterion
from app.logger import get_logger
from app.utils.api_key_manager import (
    get_default_model_name,
    get_genai_client,
    with_gemini_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


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


SECTION_ORDER = ["multiple_choice", "short_answer", "essay"]
SECTION_TO_ARRAY = {
    "multiple_choice": "multiple_choice_questions",
    "short_answer": "short_answer_questions",
    "essay": "essay_questions",
}
DEFAULT_MARKS = {"multiple_choice": 1, "short_answer": 3, "essay": 5}


SECTION_CONFIG = {
    "multiple_choice": {
        "label": "Multiple Choice",
        "required_bloom": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `multiple_choice_questions`.",
            "`choices` must contain exactly 4 non-empty strings.",
            "`correct_answer_index` must be an integer from 0 to 3.",
            "Distractors must be plausible and tied to common misconceptions.",
            "Do not include `marks` or `marking_criteria`; the system assigns 1 mark automatically.",
        ],
    },
    "short_answer": {
        "label": "Short Answer",
        "required_bloom": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `short_answer_questions`.",
            "`model_answer` must be 50-150 words.",
            "`marking_criteria` should be an array of rubric objects with `criterion`, `explanation`, and optional `marks`.",
            "Each rubric explanation must briefly state what the student must demonstrate to earn the mark(s).",
            "Questions should test understanding or application, not pure recall only.",
            "Do not include `marks`; the system assigns 3 marks automatically.",
        ],
    },
    "essay": {
        "label": "Essay",
        "required_bloom": ["understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `essay_questions`.",
            "`model_answer` must be 200-500 words.",
            "`marking_criteria` should be an array of rubric objects with `criterion`, `explanation`, and optional `marks`.",
            "Each rubric explanation must briefly state what the student must demonstrate to earn the mark(s).",
            "Questions should emphasize analysis, evaluation, or synthesis.",
            "Do not include `marks`; the system assigns 5 marks automatically.",
        ],
    },
}


BLOOM_DESCRIPTIONS = {
    "remember": "Basic Recall - Test memory of facts, definitions, terms",
    "understand": "Understanding - Test comprehension of concepts, ability to explain in own words",
    "apply": "Application - Test ability to apply concepts to new situations",
    "analyze": "Analysis - Test ability to compare, contrast, find causal relationships",
    "evaluate": "Evaluation - Test ability to judge, critique, argue",
    "create": "Creation - Test ability to design, propose new solutions",
}

DIFFICULTY_TO_BLOOM: Dict[str, List[BloomLevel]] = {
    "easy": ["remember", "understand"],
    "medium": ["understand", "apply", "analyze"],
    "difficult": ["analyze", "evaluate", "create"],
}


def _build_question_item_schema(
    question_type: str,
    *,
    bloom_enum: List[str],
    answer_description: Optional[str] = None,
) -> Dict[str, Any]:
    required = [
        "question_type",
        "bloom_level",
        "question_text",
        "rationale",
    ]
    properties: Dict[str, Any] = {
        "question_type": {"type": "string", "const": question_type},
        "bloom_level": {
            "type": "string",
            "enum": bloom_enum,
        },
        "question_text": {"type": "string"},
        "rationale": {"type": "string"},
        "image_description": {"type": ["string", "null"]},
    }

    if question_type == "multiple_choice":
        required.extend(["choices", "correct_answer_index"])
        properties["choices"] = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 4,
            "maxItems": 4,
        }
        properties["correct_answer_index"] = {
            "type": "integer",
            "minimum": 0,
            "maximum": 3,
        }
    else:
        required.extend(["model_answer", "marking_criteria"])
        properties["model_answer"] = {
            "type": "string",
            "description": answer_description,
        }
        properties["marking_criteria"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "required": ["criterion", "explanation"],
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "description": "Short rubric label, for example 'Definition Accuracy'.",
                            },
                            "explanation": {
                                "type": "string",
                                "description": "Brief scoring guidance describing what earns the mark(s).",
                            },
                            "marks": {"type": "integer", "minimum": 0},
                        },
                        "additionalProperties": False,
                    },
                ]
            },
            "minItems": 1,
        }

    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _build_generator_section_schema(question_type: str, count: int) -> Dict[str, Any]:
    array_name = SECTION_TO_ARRAY[question_type]
    config = SECTION_CONFIG[question_type]
    answer_description = None
    if question_type == "short_answer":
        answer_description = "Standard answer (50-150 words)"
    elif question_type == "essay":
        answer_description = "Reference answer (200-500 words)"

    return {
        "type": "object",
        "required": [array_name],
        "properties": {
            array_name: {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": _build_question_item_schema(
                    question_type,
                    bloom_enum=config["required_bloom"],
                    answer_description=answer_description,
                ),
            }
        },
        "additionalProperties": False,
    }


def _build_section_generator_prompt(
    *,
    context: str,
    difficulty: str,
    topic: str,
    question_type: str,
    count: int,
    feedback: str = "",
    custom_prompt: str = "",
) -> str:
    config = SECTION_CONFIG[question_type]
    array_name = SECTION_TO_ARRAY[question_type]
    bloom_levels = DIFFICULTY_TO_BLOOM.get(difficulty, DIFFICULTY_TO_BLOOM["medium"])
    bloom_desc = "\n".join(f"- {level}: {BLOOM_DESCRIPTIONS[level]}" for level in bloom_levels)
    question_specific_rules = "\n".join(f"- {rule}" for rule in config["question_specific_rules"])

    feedback_section = ""
    if feedback:
        feedback_section = f"""
## Retry / Review Feedback
{feedback}
"""

    custom_section = ""
    if custom_prompt:
        custom_section = f"""
## Additional Requirements
{custom_prompt}
"""

    return f"""You are a professional university exam question setter.

Generate ONLY the `{array_name}` section for a university exam.

## Critical Rules
1. Output exactly one JSON object.
2. The JSON object must contain ONLY the `{array_name}` field.
3. Do not output markdown, prose outside the JSON object, or code fences.
4. Every item in `{array_name}` must be a JSON object, never a bare string.
5. All questions must be answerable from the course material only.
6. Paraphrase the material instead of copying it.
7. Every question must include `question_type` and `rationale`.
8. Do not include `marks`; the system assigns marks by question type.
9. If no image is needed, set `image_description` to null.

## Section Configuration
- Exam Topic: {topic or "Infer automatically from material"}
- Difficulty Level: {difficulty}
- Section Type: {config["label"]} (`{question_type}`)
- Required Count: EXACTLY {count}
- Output Field Name: `{array_name}`

## Bloom Guidance
{bloom_desc}

## Section-Specific Requirements
{question_specific_rules}

## Rubric Guidance
- For short-answer and essay questions, prefer structured rubric objects instead of plain strings.
- Each rubric object should contain a concise `criterion` title and a concrete `explanation` of what earns the mark(s).
- Keep rubric explanations brief, specific, and tied to the expected answer.

{feedback_section}{custom_section}
## Course Material
{context}

## Output Reminder
Return valid JSON matching the provided schema, with ONLY `{array_name}` at the top level.
"""


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
    client = get_genai_client(api_key)
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

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{section_name} generation failed before receiving a response")


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
        raw_text = await with_gemini_retry_async(
            f"題目生成:{section_name}",
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


def _build_exam_name(state: Dict[str, Any], topic: str) -> str:
    explicit_exam_name = state.get("exam_name")
    if isinstance(explicit_exam_name, str) and explicit_exam_name.strip():
        return explicit_exam_name.strip()
    if isinstance(topic, str) and topic.strip():
        return topic.strip()
    return "Generated Exam"


def _distribute_marks(total_marks: int, count: int, weights: Optional[List[int]] = None) -> List[int]:
    if count <= 0:
        return []

    if weights and len(weights) == count and all(weight > 0 for weight in weights):
        total_weight = sum(weights)
        raw_allocations = [(total_marks * weight) / total_weight for weight in weights]
        assigned_marks = [int(allocation) for allocation in raw_allocations]
        remaining_marks = total_marks - sum(assigned_marks)
        ranked_indices = sorted(
            range(count),
            key=lambda idx: (raw_allocations[idx] - assigned_marks[idx], -idx),
            reverse=True,
        )
        for idx in ranked_indices[:remaining_marks]:
            assigned_marks[idx] += 1
        return assigned_marks

    base_marks, remainder = divmod(total_marks, count)
    return [base_marks + (1 if idx < remainder else 0) for idx in range(count)]


def _build_marking_scheme(question_type: str, marking_criteria: List[Any]) -> List[MarkingCriterion]:
    if question_type == "multiple_choice" or not marking_criteria:
        return []

    criteria_payload: List[Dict[str, Any]] = []
    explicit_marks: List[int] = []
    has_complete_explicit_marks = True

    for index, criterion in enumerate(marking_criteria):
        if isinstance(criterion, str):
            criteria_payload.append(
                {
                    "criterion": criterion,
                    "explanation": criterion,
                }
            )
            has_complete_explicit_marks = False
            continue

        criterion_text = criterion.get("criterion")
        explanation_text = criterion.get("explanation")
        normalized_text = criterion_text or explanation_text or f"Criterion {index + 1}"
        criteria_payload.append(
            {
                "criterion": normalized_text,
                "explanation": explanation_text or normalized_text,
            }
        )

        raw_marks = criterion.get("marks")
        if isinstance(raw_marks, int) and raw_marks > 0:
            explicit_marks.append(raw_marks)
        else:
            has_complete_explicit_marks = False

    if not criteria_payload:
        return []

    target_marks = DEFAULT_MARKS[question_type]
    if has_complete_explicit_marks and len(explicit_marks) == len(criteria_payload) and sum(explicit_marks) == target_marks:
        normalized_marks = explicit_marks
    elif has_complete_explicit_marks and len(explicit_marks) == len(criteria_payload):
        normalized_marks = _distribute_marks(target_marks, len(criteria_payload), explicit_marks)
    else:
        normalized_marks = _distribute_marks(target_marks, len(criteria_payload))

    return [
        MarkingCriterion(
            criterion=payload["criterion"],
            marks=normalized_marks[index],
            explanation=payload["explanation"],
        )
        for index, payload in enumerate(criteria_payload)
    ]


def _build_exam_question(question_type: str, raw_question: Dict[str, Any]) -> ExamQuestion:
    question_id = f"q_{uuid.uuid4().hex[:8]}"
    correct_answer_idx = None
    if question_type == "multiple_choice":
        raw_idx = raw_question.get("correct_answer_index")
        if isinstance(raw_idx, int) and 0 <= raw_idx <= 3:
            correct_answer_idx = raw_idx
        else:
            correct_answer_idx = 0
            logger.warning(
                "[Generator] Question %s has invalid correct_answer_index=%s; defaulting to 0",
                question_id,
                raw_idx,
            )

    return ExamQuestion(
        question_id=question_id,
        question_type=question_type,
        bloom_level=raw_question.get("bloom_level", "understand"),
        question_text=raw_question.get("question_text", ""),
        choices=raw_question.get("choices") if question_type == "multiple_choice" else None,
        correct_answer_index=correct_answer_idx,
        model_answer=raw_question.get("model_answer") if question_type != "multiple_choice" else None,
        marks=DEFAULT_MARKS.get(question_type, 1),
        marking_scheme=_build_marking_scheme(question_type, raw_question.get("marking_criteria") or []),
        rationale=raw_question.get("rationale", ""),
        image_description=raw_question.get("image_description"),
        source_chunk_ids=[],
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

    model_name = get_default_model_name()
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
