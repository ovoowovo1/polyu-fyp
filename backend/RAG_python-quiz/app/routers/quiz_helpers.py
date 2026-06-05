from typing import Any, Callable

from fastapi import HTTPException

from app.routers.service_helpers import require_allowed, require_teacher, run_service


def questions_from_payload(payload: dict[str, Any], *, required: bool) -> list:
    questions = payload.get("questions")
    if required and questions is None:
        raise HTTPException(status_code=400, detail="questions is required")
    if not required:
        questions = questions or []
        if not isinstance(questions, list) or not questions:
            raise HTTPException(status_code=400, detail="questions must be a non-empty list")
    return questions


def require_quiz_teacher(user: dict[str, Any], detail: str, teacher_checker: Callable[[str], bool]) -> None:
    require_teacher(user, detail, teacher_checker)


def require_class_access(user: dict[str, Any], class_id: str, class_checker: Callable[[str, str], bool]) -> None:
    require_allowed(class_checker(user["user_id"], class_id))


def require_quiz_access(user: dict[str, Any], quiz_id: str, quiz_checker: Callable[[str, str], bool]) -> None:
    require_allowed(quiz_checker(user["user_id"], quiz_id))


def require_document_access(user: dict[str, Any], file_ids: list[str], document_checker: Callable[[str, list[str]], bool]) -> None:
    require_allowed(document_checker(user["user_id"], file_ids))


def require_student(user: dict[str, Any], student_checker: Callable[[str], bool]) -> None:
    require_allowed(student_checker(user["user_id"]), "Only students can submit quizzes")


def require_create_source_access(
    user: dict[str, Any],
    *,
    class_id: str | None,
    file_ids: list[str],
    class_checker: Callable[[str, str], bool],
    document_checker: Callable[[str, list[str]], bool],
) -> None:
    if class_id:
        require_class_access(user, class_id, class_checker)
    if file_ids:
        require_document_access(user, file_ids, document_checker)
    if not class_id and not file_ids:
        require_allowed(False)


def require_score_fields(payload: dict[str, Any], detail: str) -> tuple[Any, Any]:
    score = payload.get("score")
    total_questions = payload.get("total_questions")
    if score is None or total_questions is None:
        raise HTTPException(status_code=400, detail=detail)
    return score, total_questions


async def run_quiz_service(func, *args, action: str, logger, fallback_detail=None):
    return await run_service(
        func,
        *args,
        logger=logger,
        log_message=f"{action} failed: %s",
        fallback_detail=fallback_detail or (lambda error: f"{action} failed: {error}"),
    )


def feedback_kwargs(payload: dict[str, Any], *, score: Any, total_questions: Any) -> dict[str, Any]:
    return {
        "quiz_name": payload.get("quiz_name") or "Quiz",
        "score": score,
        "total": total_questions,
        "percentage": payload.get("percentage"),
        "bloom_summary": payload.get("bloom_summary") or [],
        "questions": payload.get("questions") or [],
    }
