from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.agents.nodes.generator_config import DEFAULT_MARKS
from app.agents.schemas import ExamQuestion, MarkingCriterion
from app.logger import get_logger

logger = get_logger("app.agents.nodes.generator")


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
        return []  # pragma: no cover

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
