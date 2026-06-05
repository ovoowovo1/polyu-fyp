from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_grading_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "marks_earned": {"type": "number"},
            "feedback": {"type": "string"},
            "is_correct": {"type": "boolean"},
            "analysis": {"type": "string"},
        },
        "required": ["marks_earned", "feedback", "is_correct", "analysis"],
    }


def format_marking_criteria(marking_scheme: Optional[List[Dict[str, Any]]]) -> str:
    if not marking_scheme:
        return "No specific marking criteria provided. Use your knowledge to evaluate the answer."
    return "\n".join(
        f"- {item.get('criterion', 'Criterion')}: {item.get('marks', 0)} marks"
        for item in marking_scheme
    )


def format_reference_answer(model_answer: Optional[str]) -> str:
    if model_answer:
        return f"Reference/Model Answer:\n{model_answer}"
    return "No model answer provided. Use your knowledge to evaluate correctness based on the question."


def build_grade_answer_prompt(
    *,
    question_text: str,
    model_answer: Optional[str],
    marking_scheme: Optional[List[Dict[str, Any]]],
    student_answer: str,
    max_marks: int,
) -> str:
    return f"""
You are an objective and expert exam grader.

**Task**: Grade the student's answer based on the provided criteria.

**Question**: {question_text}
**Maximum Marks**: {max_marks}

**Marking Criteria**:
{format_marking_criteria(marking_scheme)}

{format_reference_answer(model_answer)}

**Student's Answer**:
{student_answer if student_answer else "(No answer provided)"}

**Grading Philosophy**:
1. **Prioritize Substance**: If the student's answer addresses the core requirements of the marking criteria, award full marks, even if they use different terminology or are very concise.
2. **Partial Credit**: Be generous with partial marks if a portion of the criteria is met.
3. **Reasoning First**: Analyze the answer against each criterion before deciding the final score.

**Instructions**:
- Provide feedback in 2-3 sentences max.
- Feedback should tell the student exactly what they missed (if any).
- Respond in English.

**Response Format**:
You MUST respond with valid JSON using this schema:
{{
  "analysis": "Step-by-step evaluation of the answer against the criteria",
  "marks_earned": <number>,
  "feedback": "Brief explanation",
  "is_correct": <boolean, true only if marks_earned == {max_marks}>
}}
"""


def build_exam_overall_comment_prompt(submission_summary: str, total_score: int, total_marks: int) -> str:
    return f"""You are an encouraging teacher grading an exam.

Student's Total Score: {total_score} / {total_marks}

Question Performance Summary:
{submission_summary}

**Task**: Write an overall comment for this student (approx. 3-5 sentences).

**Structure**:
1. **Praise**: Start by explicitly praising what the student did well (e.g., "You demonstrated a strong understanding of...").
2. **Improvement**: Then, gently explain the main areas that need improvement based on their mistakes (e.g., "However, you should review...").
3. **Encouragement**: End with a professional and supportive closing.

**Tone**: Professional, supportive, constructive.
**Language**: English only.

Write the comment now."""
