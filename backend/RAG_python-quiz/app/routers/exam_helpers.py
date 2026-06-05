import os
from typing import Any, Callable, List

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.routers.service_helpers import require_allowed, require_teacher, run_service


def require_teacher_user(user: dict[str, Any], detail: str, teacher_checker: Callable[[str], bool]) -> None:
    require_teacher(user, detail, teacher_checker)


def require_exam_access(user: dict[str, Any], exam_id: str, access_checker: Callable[[str, str], bool]) -> None:
    require_allowed(access_checker(user["user_id"], exam_id))


def require_teacher_exam_access(
    user: dict[str, Any],
    exam_id: str,
    detail: str,
    teacher_checker: Callable[[str], bool],
    exam_access_checker: Callable[[str, str], bool],
) -> None:
    require_teacher_user(user, detail, teacher_checker)
    require_exam_access(user, exam_id, exam_access_checker)


def require_document_access(user: dict[str, Any], file_ids: List[str], document_checker: Callable[[str, List[str]], bool]) -> None:
    require_allowed(document_checker(user["user_id"], file_ids))


async def run_exam_service(func, *args, action: str, logger):
    return await run_service(
        func,
        *args,
        logger=logger,
        log_message=f"[ExamAPI] {action.lower()} failed: %s",
        fallback_detail=lambda error: f"{action} failed: {error}",
    )


def exam_pdf_response(pdf_dir: str, exam_id: str) -> FileResponse:
    pdf_filename = f"{exam_id}.pdf"
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path=pdf_path, filename=pdf_filename, media_type="application/pdf")


def exam_image_response(images_dir: str, exam_id: str, image_name: str) -> FileResponse:
    if not image_name.startswith(exam_id):
        raise HTTPException(status_code=403, detail="Image does not belong to this exam")
    image_path = os.path.join(images_dir, image_name)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path=image_path, media_type="image/png")


def dump_grade_items(grade_items) -> list[dict[str, Any]] | None:
    return [grade.model_dump() for grade in grade_items] if grade_items else None
