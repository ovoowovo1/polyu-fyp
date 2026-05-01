from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.nodes.generator_config import (
    BLOOM_DESCRIPTIONS,
    DIFFICULTY_TO_BLOOM,
    SECTION_CONFIG,
    SECTION_TO_ARRAY,
)


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
