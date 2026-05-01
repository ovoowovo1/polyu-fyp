import asyncio
from typing import Any, Dict, List

from fastapi import HTTPException

from app.agents.graph import run_exam_generation, run_exam_generation_with_pdf
from app.agents.schemas import ExamGenerationRequest, ExamQuestion
from app.logger import get_logger
from app.services.ai_service import ai_generate_exam_overall_comment, ai_grade_answer
from app.services.pg_exam_grading_service import ai_grade_exam_submission as persist_ai_grade_exam_submission
from app.services.pg_exam_submission_service import get_submission_with_answers
from app.utils.pdf_generator import generate_exam_pdf

logger = get_logger(__name__)


async def generate_exam_with_pdf(request: ExamGenerationRequest):
    try:
        response = await run_exam_generation_with_pdf(request)
        logger.info("[ExamWorkflow] generated exam id=%s questions=%s", response.exam_id, len(response.questions))
        return response
    except ValueError as error:
        logger.error("[ExamWorkflow] validation error: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.error("[ExamWorkflow] generation failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Exam generation failed: {error}") from error


async def generate_questions_only(request: ExamGenerationRequest):
    try:
        return await run_exam_generation(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.error("[ExamWorkflow] question generation failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Question generation failed: {error}") from error


async def regenerate_exam_pdf(exam_id: str, questions: List[Any], exam_name: str) -> Dict[str, Any]:
    try:
        exam_questions = [ExamQuestion(**question) if isinstance(question, dict) else question for question in questions]
        pdf_path = await generate_exam_pdf(exam_id=exam_id, exam_name=exam_name, questions=exam_questions)
        return {"message": "PDF regenerated successfully", "exam_id": exam_id, "pdf_path": pdf_path}
    except Exception as error:
        logger.error("[ExamWorkflow] PDF regeneration failed: %s", error)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {error}") from error


def _is_real_mcq(question: Dict[str, Any]) -> bool:
    choices = question.get("choices", [])
    return question.get("question_type", "") == "multiple_choice" and choices and len(choices) > 0


def _grade_item_from_answer(answer: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "answer_id": answer.get("id"),
        "exam_question_id": answer.get("exam_question_id"),
        "marks_earned": answer.get("marks_earned", 0),
        "teacher_feedback": answer.get("teacher_feedback", ""),
        "is_correct": answer.get("is_correct", False),
        "ai_graded": False,
    }


async def _grade_answer_with_ai(answer: Dict[str, Any]):
    question = answer.get("question_snapshot", {})
    question_type = question.get("question_type", "")
    effective_type = "short_answer" if question_type == "multiple_choice" and not question.get("choices", []) else question_type
    return await ai_grade_answer(
        question_text=question.get("question_text", question.get("question", "")),
        question_type=effective_type,
        model_answer=question.get("model_answer"),
        marking_scheme=question.get("marking_scheme", []),
        student_answer=answer.get("answer_text", ""),
        max_marks=question.get("marks", 1),
    )


def _build_summary_lines(answers: List[Dict[str, Any]], graded_answers: List[Dict[str, Any]]) -> List[str]:
    summary_lines = []
    for index, graded_answer in enumerate(graded_answers):
        answer = answers[index]
        question_text = answer.get("question_snapshot", {}).get("question_text", "")
        question_text = question_text[:50] if question_text else "Question"
        max_marks = answer.get("question_snapshot", {}).get("marks", 1)
        summary_lines.append(
            f"Q{index + 1}: {question_text}... | Score: {graded_answer['marks_earned']}/{max_marks} | Correct: {graded_answer['is_correct']}"
        )
    return summary_lines


async def ai_grade_submission(submission_id: str) -> Dict[str, Any]:
    try:
        submission = await asyncio.to_thread(get_submission_with_answers, submission_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")

        answers = submission.get("answers", [])
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found in submission")

        ai_tasks = []
        answer_indices = []
        for index, answer in enumerate(answers):
            question = answer.get("question_snapshot", {})
            if _is_real_mcq(question):
                continue
            ai_tasks.append(_grade_answer_with_ai(answer))
            answer_indices.append(index)

        ai_results = await asyncio.gather(*ai_tasks, return_exceptions=True) if ai_tasks else []

        graded_answers = []
        ai_result_index = 0
        for index, answer in enumerate(answers):
            grade_item = _grade_item_from_answer(answer)
            if index in answer_indices:
                ai_result = ai_results[ai_result_index]
                ai_result_index += 1
                if isinstance(ai_result, Exception):
                    logger.error("AI grading failed for answer %s: %s", answer.get("id"), ai_result)
                    grade_item["teacher_feedback"] = f"AI grading failed: {ai_result}. Please grade manually."
                else:
                    grade_item["marks_earned"] = ai_result.get("marks_earned", 0)
                    grade_item["teacher_feedback"] = ai_result.get("feedback", "")
                    grade_item["is_correct"] = ai_result.get("is_correct", False)
                    grade_item["ai_graded"] = True
            graded_answers.append(grade_item)

        total_score = sum(item["marks_earned"] for item in graded_answers)
        total_marks = sum(answer.get("question_snapshot", {}).get("marks", 1) for answer in answers)
        overall_comment = await ai_generate_exam_overall_comment(
            submission_summary="\n".join(_build_summary_lines(answers, graded_answers)),
            total_score=total_score,
            total_marks=total_marks,
        )
        result = await asyncio.to_thread(
            persist_ai_grade_exam_submission,
            submission_id,
            graded_answers,
            teacher_comment=overall_comment,
        )
        return {"message": "AI grading completed", "submission": result, "graded_answers": graded_answers}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("[ExamWorkflow] AI grading failed: %s", error)
        raise HTTPException(status_code=500, detail=f"AI grading failed: {error}") from error


__all__ = [
    "ai_grade_submission",
    "generate_exam_with_pdf",
    "generate_questions_only",
    "regenerate_exam_pdf",
]
