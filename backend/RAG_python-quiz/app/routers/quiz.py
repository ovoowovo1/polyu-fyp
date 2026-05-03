import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query

from app.logger import get_logger
from app.routers.service_helpers import require_teacher, run_async_service
from app.services import pg_service
from app.services.ai_service import generate_quiz_feedback_text
from app.services.exceptions import ServiceError
from app.services.pg_quiz_service import QuizService, get_quiz_service
from app.services.quiz_generation_service import QuizGenerateResponse, generate_quiz_from_files
from app.utils.aqg import (
    DIFFICULTY_TO_BLOOM,
    BloomLevel,
    Difficulty,
)
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["quiz"])


def _failed_detail(action: str):
    return lambda error: f"{action} failed: {error}"


async def _run_quiz_service(
    action: str,
    func,
    *args,
    fallback_detail: Any | None = None,
):
    """Run a sync QuizService method while preserving the old router behavior.

    The original quiz router re-raised ServiceError but wrapped any other exception,
    including HTTPException raised by the mocked service layer, as a 500 response.
    This helper keeps that behavior while removing duplicated try/except blocks.
    """
    try:
        return await asyncio.to_thread(func, *args)
    except ServiceError:
        raise
    except Exception as error:
        logger.error("%s failed: %s", action, error, exc_info=True)
        detail_factory = fallback_detail or _failed_detail(action)
        resolved_detail = detail_factory(error) if callable(detail_factory) else detail_factory
        raise HTTPException(status_code=500, detail=resolved_detail) from error


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
):
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
    quiz_service: QuizService = Depends(get_quiz_service),
):
    quizzes = await _run_quiz_service(
        "Get quizzes",
        quiz_service.get_quizzes_by_class,
        class_id,
    )
    return {"message": "Fetched quizzes", "quizzes": quizzes, "total": len(quizzes)}


@router.get("/{quiz_id}")
async def get_quiz(
    quiz_id: str,
    quiz_service: QuizService = Depends(get_quiz_service),
):
    quiz_payload = await _run_quiz_service(
        "Get quiz",
        quiz_service.get_quiz_by_id,
        quiz_id,
    )
    return {"message": "Fetched quiz", "quiz": quiz_payload}


@router.post("/")
async def create_quiz(
    payload: dict = Body(...),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    questions = _questions_from_payload(payload, required=False)
    saved = await _run_quiz_service(
        "Create quiz",
        quiz_service.save_quiz,
        {"questions": questions},
        payload.get("file_ids") or [],
        payload.get("name"),
        payload.get("class_id"),
    )
    return {"message": "Quiz created", "quiz": saved}


@router.put("/{quiz_id}")
async def update_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    questions = _questions_from_payload(payload, required=True)
    updated = await _run_quiz_service(
        "Update quiz",
        quiz_service.update_quiz,
        quiz_id,
        {"questions": questions},
        payload.get("name"),
        payload.get("file_ids") if "file_ids" in payload else None,
    )
    return {"message": "Quiz updated", "quiz": updated}


@router.delete("/{quiz_id}")
async def delete_quiz(
    quiz_id: str,
    quiz_service: QuizService = Depends(get_quiz_service),
):
    return await _run_quiz_service(
        "Delete quiz",
        quiz_service.delete_quiz,
        quiz_id,
    )


@router.post("/{quiz_id}/submit")
async def submit_quiz(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="Score and total_questions required")

    return await _run_quiz_service(
        "Submit quiz",
        quiz_service.submit_quiz_result,
        quiz_id,
        user["user_id"],
        payload.get("answers", []),
        score,
        total_questions,
        fallback_detail=lambda error: str(error),
    )


@router.get("/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    require_teacher(user, "Only teachers can view all results", pg_service.is_user_teacher)
    results = await _run_quiz_service(
        "Get quiz results",
        quiz_service.get_quiz_submissions,
        quiz_id,
        fallback_detail=lambda error: str(error),
    )
    return {"results": results}


@router.get("/{quiz_id}/my-result")
async def get_my_quiz_result(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    result = await _run_quiz_service(
        "Get my result",
        quiz_service.get_student_quiz_submission,
        quiz_id,
        user["user_id"],
        fallback_detail=lambda error: str(error),
    )
    return {"submission": result} if result else {"submission": None}


@router.post("/{quiz_id}/feedback")
async def generate_quiz_feedback(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    del quiz_id, user
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
