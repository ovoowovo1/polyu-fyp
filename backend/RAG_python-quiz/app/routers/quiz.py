import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.logger import get_logger
from app.services import pg_service
from app.services.ai_service import generate_quiz_feedback_text
from app.utils.api_key_manager import get_genai_client, with_gemini_retry_async
from app.utils.aqg import (
    DIFFICULTY_TO_BLOOM,
    BloomLevel,
    Difficulty,
    MultipleChoice,
    _QuizWithName,
    build_prompt,
    distribute_counts,
    maybe_truncate_or_summarize,
)
from app.utils.jwt_utils import get_current_user
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["quiz"])


class QuizGenerateResponse(BaseModel):
    questions: List[MultipleChoice]
    source_text_length: int
    was_summarized: bool


def _looks_like_quiz_not_found(error: Exception) -> bool:
    message = str(error)
    lowered = message.lower()
    return "not found" in lowered or any([ord(ch) > 127 for ch in message])


def _merge_selected_levels(bloom_levels: Optional[List[BloomLevel]], difficulty: Optional[Difficulty]) -> List[BloomLevel]:
    selected_levels = list(dict.fromkeys(bloom_levels or []))
    if difficulty:
        mapped_levels = DIFFICULTY_TO_BLOOM[difficulty]
        if selected_levels:
            for level in mapped_levels:
                if level not in selected_levels:
                    selected_levels.append(level)
        else:
            selected_levels = mapped_levels.copy()
    if not selected_levels:
        selected_levels = DIFFICULTY_TO_BLOOM["easy"].copy()
    return selected_levels


async def _load_source_text(file_ids: List[str]) -> str:
    try:
        source_text = await asyncio.to_thread(pg_service.get_files_text_content, file_ids)
    except Exception as error:
        raise HTTPException(status_code=404, detail=f"Failed to load source content: {error}") from error
    if not source_text or not source_text.strip():
        raise HTTPException(status_code=400, detail="Source files contain no usable text")
    return source_text


async def _resolve_class_id(file_ids: List[str]) -> str:
    try:
        from app.services.pg_db import _get_conn

        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT class_id FROM documents WHERE id = ANY(%s::uuid[])", (file_ids,))
            rows = cur.fetchall()
            if len(rows) != 1 or not rows[0]["class_id"]:
                raise HTTPException(status_code=400, detail="Files must belong to exactly one class")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Failed to resolve class: {error}") from error

    return str(rows[0]["class_id"])


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(file_ids: List[str] = Form(...), bloom_levels: Optional[List[BloomLevel]] = Form(None), difficulty: Optional[Difficulty] = Form(None), num_questions: int = Form(5)):
    logger.debug("[Quiz] request file_ids=%s bloom_levels=%s difficulty=%s num_questions=%s", file_ids, bloom_levels, difficulty, num_questions)
    try:
        if not file_ids:
            raise HTTPException(status_code=400, detail="At least one file id is required")
        if num_questions < 1 or num_questions >= 100:
            raise HTTPException(status_code=400, detail="num_questions must be between 1 and 99")

        selected_levels = _merge_selected_levels(bloom_levels, difficulty)
        source_text = await _load_source_text(file_ids)
        class_id = await _resolve_class_id(file_ids)

        settings = get_settings()
        model_name = settings.google_ai_model or "gemini-2.5-flash"
        processed_text = source_text
        was_summarized = False

        if len(source_text) > 12000:
            async def _summarize_text(api_key: str, raw_source_text: str, raw_model_name: str):
                client = get_genai_client(api_key)
                return await asyncio.to_thread(maybe_truncate_or_summarize, client, raw_model_name, raw_source_text)

            processed_text = await with_gemini_retry_async("quiz_summary", _summarize_text, source_text, model_name, error_type=HTTPException)
            was_summarized = True

        prompt = build_prompt(processed_text, distribute_counts(num_questions, selected_levels))

        async def _generate_quiz_with_model(api_key: str, quiz_prompt: str, raw_model_name: str):
            client = get_genai_client(api_key)
            logger.info("[Quiz] generating quiz content")
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=raw_model_name,
                messages=[{"role": "user", "content": quiz_prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "quiz_generation",
                        "strict": True,
                        "schema": _QuizWithName.model_json_schema(),
                    },
                },
            )
            raw_text = extract_chat_completion_text(response, "Quiz generation")
            if not raw_text:
                raise RuntimeError("API returned empty content")
            quiz_payload = json.loads(raw_text)
            questions = [MultipleChoice(**item) for item in quiz_payload.get("questions", [])]
            quiz_name = quiz_payload.get("quiz_name")
            logger.info("[Quiz] generated quiz name=%s questions=%s", quiz_name, len(questions))
            return {"quiz_name": quiz_name, "questions": questions}

        try:
            generated = await with_gemini_retry_async("quiz_generation", _generate_quiz_with_model, prompt, model_name, error_type=HTTPException)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=500, detail=f"Invalid Gemini JSON response: {error}") from error

        quiz_response = QuizGenerateResponse(
            questions=generated["questions"],
            source_text_length=len(processed_text),
            was_summarized=was_summarized,
        )

        try:
            quiz_data = {
                "questions": [question.model_dump() for question in generated["questions"]],
                "source_text_length": len(processed_text),
                "was_summarized": was_summarized,
            }
            saved_info = await asyncio.to_thread(pg_service.save_quiz, quiz_data, file_ids, generated["quiz_name"], class_id)
            logger.info("[Quiz] saved quiz id=%s name=%s", saved_info["quiz_id"], saved_info.get("name", "N/A"))
        except Exception as save_error:
            logger.error("[Quiz] failed to save quiz: %s", save_error)

        return quiz_response
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {error}") from error


@router.get("/bloom-levels")
async def get_bloom_levels():
    from app.utils.aqg import BLOOM_DESCRIPTIONS

    return {"levels": [{"value": level, "description": description} for level, description in BLOOM_DESCRIPTIONS.items()]}


@router.get("/difficulties")
async def get_difficulties():
    return {"difficulties": [{"value": difficulty, "bloom_levels": levels} for difficulty, levels in DIFFICULTY_TO_BLOOM.items()]}


@router.get("/list")
async def get_all_quizzes(class_id: str = Query(...)):
    try:
        quizzes = await asyncio.to_thread(pg_service.get_quizzes_by_class, class_id)
        return {"message": "Fetched quizzes", "quizzes": quizzes, "total": len(quizzes)}
    except Exception as error:
        logger.error("Get quizzes failed: %s", error)
        raise HTTPException(status_code=500, detail=f"Get quizzes failed: {error}") from error


@router.get("/{quiz_id}")
async def get_quiz(quiz_id: str):
    try:
        quiz_payload = await asyncio.to_thread(pg_service.get_quiz_by_id, quiz_id)
        return {"message": "Fetched quiz", "quiz": quiz_payload}
    except Exception as error:
        if _looks_like_quiz_not_found(error):
            raise HTTPException(status_code=404, detail="Quiz not found") from error
        raise HTTPException(status_code=500, detail=f"Get quiz failed: {error}") from error


@router.post("/")
async def create_quiz(payload: dict = Body(...)):
    try:
        questions = payload.get("questions") or []
        if not isinstance(questions, list) or not questions:
            raise HTTPException(status_code=400, detail="questions must be a non-empty list")
        file_ids = payload.get("file_ids") or []
        saved = await asyncio.to_thread(pg_service.save_quiz, {"questions": questions}, file_ids, payload.get("name"), payload.get("class_id"))
        return {"message": "Quiz created", "quiz": saved}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Create quiz failed: %s", error)
        raise HTTPException(status_code=500, detail=f"Create quiz failed: {error}") from error


@router.put("/{quiz_id}")
async def update_quiz(quiz_id: str, payload: dict = Body(...)):
    try:
        questions = payload.get("questions")
        if questions is None:
            raise HTTPException(status_code=400, detail="questions is required")
        updated = await asyncio.to_thread(
            pg_service.update_quiz,
            quiz_id,
            {"questions": questions},
            payload.get("name"),
            payload.get("file_ids") if "file_ids" in payload else None,
        )
        return {"message": "Quiz updated", "quiz": updated}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Update quiz failed: %s", error)
        if _looks_like_quiz_not_found(error):
            raise HTTPException(status_code=404, detail="Quiz not found") from error
        raise HTTPException(status_code=500, detail=f"Update quiz failed: {error}") from error


@router.delete("/{quiz_id}")
async def delete_quiz(quiz_id: str):
    try:
        return await asyncio.to_thread(pg_service.delete_quiz, quiz_id)
    except Exception as error:
        if _looks_like_quiz_not_found(error):
            raise HTTPException(status_code=404, detail="Quiz not found") from error
        raise HTTPException(status_code=500, detail=f"Delete quiz failed: {error}") from error


@router.post("/{quiz_id}/submit")
async def submit_quiz(quiz_id: str, payload: dict = Body(...), user: dict = Depends(get_current_user)):
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail="Score and total_questions required")
    try:
        return await asyncio.to_thread(pg_service.submit_quiz_result, quiz_id, user["user_id"], payload.get("answers", []), score, total_questions)
    except Exception as error:
        logger.error("Submit quiz failed: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/{quiz_id}/results")
async def get_quiz_results(quiz_id: str, user: dict = Depends(get_current_user)):
    try:
        if not pg_service.is_user_teacher(user["user_id"]):
            raise HTTPException(status_code=403, detail="Only teachers can view all results")
        return {"results": await asyncio.to_thread(pg_service.get_quiz_submissions, quiz_id)}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Get quiz results failed: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/{quiz_id}/my-result")
async def get_my_quiz_result(quiz_id: str, user: dict = Depends(get_current_user)):
    try:
        result = await asyncio.to_thread(pg_service.get_student_quiz_submission, quiz_id, user["user_id"])
        return {"submission": result} if result else {"submission": None}
    except Exception as error:
        logger.error("Get my result failed: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


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

