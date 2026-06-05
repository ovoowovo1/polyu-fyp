from typing import List

from app.agents.schemas import ExamQuestion


def format_marking_scheme(question: ExamQuestion) -> str:
    if not question.marking_scheme:
        return "N/A"

    parts = []
    for criterion in question.marking_scheme:
        explanation = ""
        if criterion.explanation and criterion.explanation != criterion.criterion:
            explanation = f" ({criterion.explanation})"
        parts.append(f"{criterion.criterion} [{criterion.marks} mark(s)]{explanation}")
    return "; ".join(parts)


def build_review_prompt(
    context: str,
    questions: List[ExamQuestion],
    custom_prompt: str = "",
    has_images: bool = False,
) -> str:
    questions_text = ""
    for index, question in enumerate(questions, 1):
        if question.image_description:
            if question.image_path:
                image_info = (
                    f"Yes - Image Description: {question.image_description} "
                    "(Image attached below, please review together)"
                )
            else:
                image_info = f"Yes - {question.image_description} (Image generation failed)"
        else:
            image_info = "No"

        options_text = ", ".join(question.choices) if question.choices else "N/A"
        correct_answer_text = "N/A"
        if (
            question.choices
            and question.correct_answer_index is not None
            and 0 <= question.correct_answer_index < len(question.choices)
        ):
            correct_answer_text = question.choices[question.correct_answer_index]

        questions_text += f"""
### Question {index} (ID: {question.question_id})
- Question Type: {question.question_type}
- Bloom Level: {question.bloom_level}
- Marks: {question.marks}
- Question: {question.question_text}
- Options: {options_text}
- Correct Answer: {correct_answer_text}
- Reference Answer / Model Answer: {question.model_answer or 'N/A'}
- Marking Scheme / Rubric: {format_marking_scheme(question)}
- Explanation: {question.rationale}
- Attached Image: {image_info}
"""

    image_review_note = ""
    if has_images:
        image_review_note = """
## Image Review Instructions
This review includes images. Check:
- whether the image matches the question description
- whether the image is clear and helpful
- whether the image style is suitable for educational use
"""

    custom_req_note = ""
    if custom_prompt:
        custom_req_note = f"""
## User Custom Requirements (CRITICAL)
The user explicitly requested: "{custom_prompt}"
You MUST check whether the generated questions meet these requirements.
- If a requested topic is missing, use decision "RESEARCH" and set `research_goal`.
- If a requested format or style is not followed, mention it in the issues.
"""

    return f"""You are a senior exam review expert. Review the following exam questions generated from the course material.

## Review Criteria
1. User requirements compliance
2. Content accuracy
3. Answer correctness
4. Question clarity
5. Bloom level appropriateness
6. Chart/image reasonableness
{image_review_note}
{custom_req_note}

## Course Material Summary
{context}...

## Questions to Review
{questions_text}

## Serious Errors
Mark `is_valid = false` if any of the following is true:
- the answer is obviously wrong
- the question is irrelevant to the course material
- multiple options could be correct in a multiple-choice question
- a short-answer or essay question is missing `model_answer`
- any question is missing a usable marking scheme / rubric

## Question-Type Guidance
- `multiple_choice` questions should include options and a single correct answer.
- `short_answer` and `essay` are valid open-response formats and should not be marked wrong just because they do not have options.
- Only use `marking_unclear` for `short_answer` or `essay` when `model_answer` or the marking scheme is missing, vague, or unusable.

## Decision Logic
- PASS: questions are good and valid
- REWRITE: questions are poor, but the course material is sufficient
- RESEARCH: the course material is missing key information; provide a concrete `research_goal`

## Output Format Requirements
Return valid JSON matching the schema.

Important reminders:
1. `issues` must be `[]` if no problems exist.
2. `overall_score` must be between 0 and 100.
3. Use `issue_type` from: context_mismatch, answer_error, marking_unclear, image_issue.
"""
