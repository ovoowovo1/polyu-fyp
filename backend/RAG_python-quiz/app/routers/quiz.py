from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query

from app.logger import get_logger
from app.routers.service_helpers import require_teacher
from app.services import pg_service
from app.services.pg_quiz_service import QuizService, get_quiz_service
from app.services.ai_service import generate_quiz_feedback_text
from app.services.quiz_generation_service import QuizGenerateResponse, generate_quiz_from_files
from app.utils.aqg import (
    DIFFICULTY_TO_BLOOM,
    BloomLevel,
    Difficulty,
)
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["quiz"])


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(file_ids: List[str] = Form(...), bloom_levels: Optional[List[BloomLevel]] = Form(None), difficulty: Optional[Difficulty] = Form(None), num_questions: int = Form(5)):
    return await generate_quiz_from_files(file_ids, bloom_levels, difficulty, num_questions)


@router.get("/bloom-levels")
async def get_bloom_levels():
    from app.utils.aqg import BLOOM_DESCRIPTIONS

    return {"levels": [{"value": level, "description": description} for level, description in BLOOM_DESCRIPTIONS.items()]}


@router.get("/difficulties")
async def get_difficulties():
    return {"difficulties": [{"value": difficulty, "bloom_levels": levels} for difficulty, levels in DIFFICULTY_TO_BLOOM.items()]}


@router.get("/list")
def get_all_quizzes(class_id: str = Query(...), quiz_service: QuizService = Depends(get_quiz_service)):
    try:
        quizzes = quiz_service.get_quizzes_by_class(class_id)
        return {"message": "Fetched quizzes", "quizzes": quizzes, "total": len(quizzes)}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Get quizzes failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Get quizzes failed: {error}")


@router.get("/{quiz_id}")
def get_quiz(quiz_id: str, quiz_service: QuizService = Depends(get_quiz_service)):
    try:
        quiz_payload = quiz_service.get_quiz_by_id(quiz_id)
        return {"message": "Fetched quiz", "quiz": quiz_payload}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Get quiz failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Get quiz failed: {error}")


@router.post("/")
def create_quiz(payload: dict = Body(...), quiz_service: QuizService = Depends(get_quiz_service)):
    questions = payload.get("questions") or []
    if not isinstance(questions, list) or not questions:
        raise HTTPException(status_code=400, detail="questions must be a non-empty list")
    file_ids = payload.get("file_ids") or []
    try:
        saved = quiz_service.save_quiz(
            {"questions": questions},
            file_ids,
            payload.get("name"),
            payload.get("class_id"),
        )
        return {"message": "Quiz created", "quiz": saved}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Create quiz failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Create quiz failed: {error}")


@router.put("/{quiz_id}")
def update_quiz(quiz_id: str, payload: dict = Body(...), quiz_service: QuizService = Depends(get_quiz_service)):
    questions = payload.get("questions")
    if questions is None:
        raise HTTPException(status_code=400, detail="questions is required")
    try:
        updated = quiz_service.update_quiz(
            quiz_id,
            {"questions": questions},
            payload.get("name"),
            payload.get("file_ids") if "file_ids" in payload else None,
        )
        return {"message": "Quiz updated", "quiz": updated}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Update quiz failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Update quiz failed: {error}")


@router.delete("/{quiz_id}")
def delete_quiz(quiz_id: str, quiz_service: QuizService = Depends(get_quiz_service)):
    try:
        return quiz_service.delete_quiz(quiz_id)
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Delete quiz failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Delete quiz failed: {error}")


@router.post("/{quiz_id}/submit")
def submit_quiz(quiz_id: str, payload: dict = Body(...), user: dict = Depends(get_current_user), quiz_service: QuizService = Depends(get_quiz_service)):
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="Score and total_questions required")
    try:
        return quiz_service.submit_quiz_result(
            quiz_id,
            user["user_id"],
            payload.get("answers", []),
            score,
            total_questions,
        )
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Submit quiz failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/{quiz_id}/results")
def get_quiz_results(quiz_id: str, user: dict = Depends(get_current_user), quiz_service: QuizService = Depends(get_quiz_service)):
    require_teacher(user, "Only teachers can view all results", pg_service.is_user_teacher)
    try:
        results = quiz_service.get_quiz_submissions(quiz_id)
        return {"results": results}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Get quiz results failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/{quiz_id}/my-result")
def get_my_quiz_result(quiz_id: str, user: dict = Depends(get_current_user), quiz_service: QuizService = Depends(get_quiz_service)):
    try:
        result = quiz_service.get_student_quiz_submission(quiz_id, user["user_id"])
        return {"submission": result} if result else {"submission": None}
    except Exception as error:
        from app.services.exceptions import ServiceError
        if isinstance(error, ServiceError): raise
        logger.error(f"Get my result failed: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/{quiz_id}/feedback")
async def generate_quiz_feedback(quiz_id: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
    del quiz_id, user
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="score and total_questions are required")
    try:
        feedback_text = await generate_quiz_feedback_text(
            quiz_name=payload.get("quiz_name") or "Quiz",
            score=score,
            total=total_questions,
            percentage=payload.get("percentage"),
            bloom_summary=payload.get("bloom_summary") or [],
            questions=payload.get("questions") or [],
        )
        return {"feedback": feedback_text}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Generate feedback failed: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error

