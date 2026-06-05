from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query

from app.logger import get_logger
from app.routers.service_helpers import require_allowed, require_teacher, run_async_service, run_service
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
    questions = payload.get("questions")
    if required and questions is None:
        raise HTTPException(status_code=400, detail="questions is required")
    if not required:
        questions = questions or []
        if not isinstance(questions, list) or not questions:
            raise HTTPException(status_code=400, detail="questions must be a non-empty list")
    return questions


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(
    file_ids: List[str] = Form(...),
    bloom_levels: Optional[List[BloomLevel]] = Form(None),
    difficulty: Optional[Difficulty] = Form(None),
    num_questions: int = Form(5),
    user: dict = Depends(get_current_user),
):
    require_teacher(user, "Only teachers can generate quizzes", is_user_teacher)
    require_allowed(pg_service.can_manage_documents(user["user_id"], file_ids))
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
    require_allowed(pg_service.can_access_class(user["user_id"], class_id))
    quizzes = await run_service(
        pg_quiz_service.get_quizzes_by_class,
        class_id,
        user["user_id"],
        logger=logger,
        log_message="Get quizzes failed: %s",
        fallback_detail=lambda error: f"Get quizzes failed: {error}",
    )
    return {"message": "Fetched quizzes", "quizzes": quizzes, "total": len(quizzes)}


@router.get("/{quiz_id}")
async def get_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    quiz_payload = await run_service(
        pg_quiz_service.get_quiz_by_id,
        quiz_id,
        user["user_id"],
        logger=logger,
        log_message="Get quiz failed: %s",
        fallback_detail=lambda error: f"Get quiz failed: {error}",
    )
    return {"message": "Fetched quiz", "quiz": quiz_payload}


@router.post("/")
async def create_quiz(
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    require_teacher(user, "Only teachers can create quizzes", is_user_teacher)
    questions = _questions_from_payload(payload, required=False)
    file_ids = payload.get("file_ids") or []
    class_id = payload.get("class_id")
    if class_id:
        require_allowed(pg_service.can_access_class(user["user_id"], class_id))
    if file_ids:
        require_allowed(pg_service.can_manage_documents(user["user_id"], file_ids))
    if not class_id and not file_ids:
        require_allowed(False)
    saved = await run_service(
        pg_quiz_service.save_quiz,
        {"questions": questions},
        file_ids,
        payload.get("name"),
        class_id,
        logger=logger,
        log_message="Create quiz failed: %s",
        fallback_detail=lambda error: f"Create quiz failed: {error}",
    )
    return {"message": "Quiz created", "quiz": saved}


@router.put("/{quiz_id}")
async def update_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    require_teacher(user, "Only teachers can update quizzes", is_user_teacher)
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    questions = _questions_from_payload(payload, required=True)
    if payload.get("file_ids"):
        require_allowed(pg_service.can_manage_documents(user["user_id"], payload["file_ids"]))
    updated = await run_service(
        pg_quiz_service.update_quiz,
        quiz_id,
        {"questions": questions},
        payload.get("name"),
        payload.get("file_ids") if "file_ids" in payload else None,
        logger=logger,
        log_message="Update quiz failed: %s",
        fallback_detail=lambda error: f"Update quiz failed: {error}",
    )
    return {"message": "Quiz updated", "quiz": updated}


@router.delete("/{quiz_id}")
async def delete_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    require_teacher(user, "Only teachers can delete quizzes", is_user_teacher)
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    return await run_service(
        pg_quiz_service.delete_quiz,
        quiz_id,
        user["user_id"],
        logger=logger,
        log_message="Delete quiz failed: %s",
        fallback_detail=lambda error: f"Delete quiz failed: {error}",
    )


@router.post("/{quiz_id}/submit")
async def submit_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    require_allowed(pg_service.is_user_student(user["user_id"]), "Only students can submit quizzes")
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="Score and total_questions required")

    return await run_service(
        pg_quiz_service.submit_quiz_result,
        quiz_id,
        user["user_id"],
        payload.get("answers", []),
        score,
        total_questions,
        logger=logger,
        log_message="Submit quiz failed: %s",
        fallback_detail=lambda error: str(error),
    )


@router.get("/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    require_teacher(user, "Only teachers can view all results", is_user_teacher)
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    results = await run_service(
        pg_quiz_service.get_quiz_submissions,
        quiz_id,
        user["user_id"],
        logger=logger,
        log_message="Get quiz results failed: %s",
        fallback_detail=lambda error: str(error),
    )
    return {"results": results}


@router.get("/{quiz_id}/my-result")
async def get_my_quiz_result(
    quiz_id: str,
    user: dict = Depends(get_current_user),
):
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    result = await run_service(
        pg_quiz_service.get_student_quiz_submission,
        quiz_id,
        user["user_id"],
        logger=logger,
        log_message="Get my result failed: %s",
        fallback_detail=lambda error: str(error),
    )
    return {"submission": result} if result else {"submission": None}


@router.post("/{quiz_id}/feedback")
async def generate_quiz_feedback(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    require_allowed(pg_service.can_access_quiz(user["user_id"], quiz_id))
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="score and total_questions are required")

    feedback_text = await run_async_service(
        generate_quiz_feedback_text,
        quiz_name=payload.get("quiz_name") or "Quiz",
        score=score,
        total=total_questions,
        percentage=payload.get("percentage"),
        bloom_summary=payload.get("bloom_summary") or [],
        questions=payload.get("questions") or [],
        logger=logger,
        log_message="Generate feedback failed: %s",
        fallback_detail=lambda error: str(error),
    )
    return {"feedback": feedback_text}
