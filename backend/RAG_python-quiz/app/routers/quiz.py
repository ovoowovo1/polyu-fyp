from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Form, Query

from app.logger import get_logger
from app.routers import quiz_helpers
from app.routers.service_helpers import run_async_service
from app.services.pg import pg_access_control as pg_service
from app.services.pg import pg_quiz_service
from app.services.pg.pg_classes_service import is_user_teacher
from app.services.ai.quiz_feedback_service import generate_quiz_feedback_text
from app.services.assessment.quiz_generation_service import QuizGenerateResponse, generate_quiz_from_files
from app.utils.aqg import (
    DIFFICULTY_TO_BLOOM,
    BloomLevel,
    Difficulty,
)
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["quiz"])


def _questions_from_payload(payload: dict, *, required: bool) -> list:
    return quiz_helpers.questions_from_payload(payload, required=required)


async def _run_quiz_service(func, *args, action: str, fallback_detail=None):
    return await quiz_helpers.run_quiz_service(
        func,
        *args,
        action=action,
        logger=logger,
        fallback_detail=fallback_detail,
    )


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(
    file_ids: List[str] = Form(...),
    bloom_levels: Optional[List[BloomLevel]] = Form(None),
    difficulty: Optional[Difficulty] = Form(None),
    num_questions: int = Form(5),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_teacher(user, "Only teachers can generate quizzes", is_user_teacher)
    quiz_helpers.require_document_access(user, file_ids, pg_service.can_manage_documents)
    return await generate_quiz_from_files(file_ids, bloom_levels, difficulty, num_questions)


@router.get("/bloom-levels")
async def get_bloom_levels():
    from app.utils.aqg import BLOOM_DESCRIPTIONS

    return {
        "levels": [
            {"value": level, "description": description}
            for level, description in BLOOM_DESCRIPTIONS.items()
        ]
    }


@router.get("/difficulties")
async def get_difficulties():
    return {
        "difficulties": [
            {"value": difficulty, "bloom_levels": levels}
            for difficulty, levels in DIFFICULTY_TO_BLOOM.items()
        ]
    }


@router.get("/list")
async def get_all_quizzes(
    class_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_class_access(user, class_id, pg_service.can_access_class)
    quizzes = await _run_quiz_service(
        pg_quiz_service.get_quizzes_by_class,
        class_id,
        user["user_id"],
        action="Get quizzes",
    )
    return {"message": "Fetched quizzes", "quizzes": quizzes, "total": len(quizzes)}


@router.get("/{quiz_id}")
async def get_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    quiz_payload = await _run_quiz_service(
        pg_quiz_service.get_quiz_by_id,
        quiz_id,
        user["user_id"],
        action="Get quiz",
    )
    return {"message": "Fetched quiz", "quiz": quiz_payload}


@router.post("/")
async def create_quiz(
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_teacher(user, "Only teachers can create quizzes", is_user_teacher)
    questions = _questions_from_payload(payload, required=False)
    file_ids = payload.get("file_ids") or []
    class_id = payload.get("class_id")
    quiz_helpers.require_create_source_access(
        user,
        class_id=class_id,
        file_ids=file_ids,
        class_checker=pg_service.can_access_class,
        document_checker=pg_service.can_manage_documents,
    )
    saved = await _run_quiz_service(
        pg_quiz_service.save_quiz,
        {"questions": questions},
        file_ids,
        payload.get("name"),
        class_id,
        action="Create quiz",
    )
    return {"message": "Quiz created", "quiz": saved}


@router.put("/{quiz_id}")
async def update_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_teacher(user, "Only teachers can update quizzes", is_user_teacher)
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    questions = _questions_from_payload(payload, required=True)
    if payload.get("file_ids"):
        quiz_helpers.require_document_access(user, payload["file_ids"], pg_service.can_manage_documents)
    updated = await _run_quiz_service(
        pg_quiz_service.update_quiz,
        quiz_id,
        {"questions": questions},
        payload.get("name"),
        payload.get("file_ids") if "file_ids" in payload else None,
        action="Update quiz",
    )
    return {"message": "Quiz updated", "quiz": updated}


@router.delete("/{quiz_id}")
async def delete_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_teacher(user, "Only teachers can delete quizzes", is_user_teacher)
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    return await _run_quiz_service(
        pg_quiz_service.delete_quiz,
        quiz_id,
        user["user_id"],
        action="Delete quiz",
    )


@router.post("/{quiz_id}/submit")
async def submit_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_student(user, pg_service.is_user_student)
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    score, total_questions = quiz_helpers.require_score_fields(payload, "Score and total_questions required")

    return await _run_quiz_service(
        pg_quiz_service.submit_quiz_result,
        quiz_id,
        user["user_id"],
        payload.get("answers", []),
        score,
        total_questions,
        action="Submit quiz",
        fallback_detail=lambda error: str(error),
    )


@router.get("/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_teacher(user, "Only teachers can view all results", is_user_teacher)
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    results = await _run_quiz_service(
        pg_quiz_service.get_quiz_submissions,
        quiz_id,
        user["user_id"],
        action="Get quiz results",
        fallback_detail=lambda error: str(error),
    )
    return {"results": results}


@router.get("/{quiz_id}/my-result")
async def get_my_quiz_result(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    result = await _run_quiz_service(
        pg_quiz_service.get_student_quiz_submission,
        quiz_id,
        user["user_id"],
        action="Get my result",
        fallback_detail=lambda error: str(error),
    )
    return {"submission": result} if result else {"submission": None}


@router.post("/{quiz_id}/feedback")
async def generate_quiz_feedback(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    quiz_helpers.require_quiz_access(user, quiz_id, pg_service.can_access_quiz)
    score, total_questions = quiz_helpers.require_score_fields(payload, "score and total_questions are required")

    feedback_text = await run_async_service(
        generate_quiz_feedback_text,
        **quiz_helpers.feedback_kwargs(payload, score=score, total_questions=total_questions),
        logger=logger,
        log_message="Generate feedback failed: %s",
        fallback_detail=lambda error: str(error),
    )
    return {"feedback": feedback_text}
