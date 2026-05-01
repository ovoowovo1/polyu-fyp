import asyncio
import json
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.logger import get_logger
from app.services import pg_service
from app.utils.api_key_manager import get_llm_client, with_llm_retry_async
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
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


class QuizGenerateResponse(BaseModel):
    questions: List[MultipleChoice]
    source_text_length: int
    was_summarized: bool


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


async def _summarize_text(api_key: str, raw_source_text: str, raw_model_name: str):
    client = get_llm_client(api_key)
    return await asyncio.to_thread(maybe_truncate_or_summarize, client, raw_model_name, raw_source_text)


async def _generate_quiz_with_model(api_key: str, quiz_prompt: str, raw_model_name: str):
    client = get_llm_client(api_key)
    logger.info("[QuizGeneration] generating quiz content")
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
    logger.info("[QuizGeneration] generated quiz name=%s questions=%s", quiz_name, len(questions))
    return {"quiz_name": quiz_name, "questions": questions}


async def generate_quiz_from_files(
    file_ids: List[str],
    bloom_levels: Optional[List[BloomLevel]],
    difficulty: Optional[Difficulty],
    num_questions: int,
) -> QuizGenerateResponse:
    logger.debug(
        "[QuizGeneration] request file_ids=%s bloom_levels=%s difficulty=%s num_questions=%s",
        file_ids,
        bloom_levels,
        difficulty,
        num_questions,
    )
    try:
        if not file_ids:
            raise HTTPException(status_code=400, detail="At least one file id is required")
        if num_questions < 1 or num_questions >= 100:
            raise HTTPException(status_code=400, detail="num_questions must be between 1 and 99")

        selected_levels = _merge_selected_levels(bloom_levels, difficulty)
        source_text = await _load_source_text(file_ids)
        class_id = await _resolve_class_id(file_ids)

        settings = get_settings()
        model_name = settings.llm_model or "gemini-2.5-flash"
        processed_text = source_text
        was_summarized = False

        if len(source_text) > 12000:
            processed_text = await with_llm_retry_async(
                "quiz_summary",
                _summarize_text,
                source_text,
                model_name,
                error_type=HTTPException,
            )
            was_summarized = True

        prompt = build_prompt(processed_text, distribute_counts(num_questions, selected_levels))

        try:
            generated = await with_llm_retry_async(
                "quiz_generation",
                _generate_quiz_with_model,
                prompt,
                model_name,
                error_type=HTTPException,
            )
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
            logger.info("[QuizGeneration] saved quiz id=%s name=%s", saved_info["quiz_id"], saved_info.get("name", "N/A"))
        except Exception as save_error:
            logger.error("[QuizGeneration] failed to save quiz: %s", save_error)

        return quiz_response
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {error}") from error


__all__ = ["QuizGenerateResponse", "generate_quiz_from_files"]
