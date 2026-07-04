import os
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query, Response
from pydantic import BaseModel, model_validator

from app.agents.schemas import ExamGenerationRequest, ExamGenerationResponse
from app.logger import get_logger
from app.api_helpers import exam_helpers
from app.api_helpers.service_helpers import require_allowed, run_service
from app.services.assessment import exam_workflow_service
from app.services.cache import redis_cache
from app.services.cache import studio_cache
from app.services.pg.pg_access_control import (
    can_access_class,
    can_access_exam,
    can_manage_documents,
    require_submission_owner,
    require_submission_teacher,
)
from app.services.pg.pg_classes_service import is_user_teacher
from app.services.pg.pg_exam_crud import (
    delete_exam as delete_exam_record,
    get_exam_by_id,
    get_exams_by_class,
    publish_exam as publish_exam_record,
    update_exam as update_exam_record,
)
from app.services.pg.pg_exam_grading_service import grade_exam_submission
from app.services.pg.pg_exam_submission_service import (
    get_exam_submissions as get_exam_submission_rows,
    get_student_exam_submissions,
    start_exam_submission,
    submit_exam as submit_exam_submission,
)
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)
router = APIRouter(prefix="/exam", tags=["exam"])


class ExamUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    questions: Optional[List[dict]] = None
    difficulty: Optional[str] = None
    duration_minutes: Optional[int] = None
    file_ids: Optional[List[str]] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None


class ExamStartResponse(BaseModel):
    submission_id: str
    started_at: str
    attempt_no: int
    duration_minutes: Optional[int] = None


class ExamSubmitRequest(BaseModel):
    answers: List[dict]
    time_spent_seconds: Optional[int] = None


class GradeAnswerItem(BaseModel):
    answer_id: Optional[str] = None
    exam_question_id: Optional[str] = None
    marks_earned: int
    teacher_feedback: Optional[str] = None

    @model_validator(mode="after")
    def validate_identifiers(self):
        if not self.answer_id and not self.exam_question_id:
            raise ValueError("Either answer_id or exam_question_id is required")
        return self


class GradeSubmissionRequest(BaseModel):
    answers_grades: Optional[List[GradeAnswerItem]] = None
    teacher_comment: Optional[str] = None


PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "pdfs")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "images")


def _require_teacher(user: dict, detail: str) -> None:
    exam_helpers.require_teacher_user(user, detail, is_user_teacher)


def _require_exam_access(user: dict, exam_id: str) -> None:
    exam_helpers.require_exam_access(user, exam_id, can_access_exam)


def _require_teacher_exam_access(user: dict, exam_id: str, detail: str) -> None:
    exam_helpers.require_teacher_exam_access(user, exam_id, detail, is_user_teacher, can_access_exam)


def _require_document_access(user: dict, file_ids: List[str]) -> None:
    exam_helpers.require_document_access(user, file_ids, can_manage_documents)


async def _run_exam_service(func, *args, action: str):
    return await exam_helpers.run_exam_service(func, *args, action=action, logger=logger)


@router.post("/generate", response_model=ExamGenerationResponse)
async def generate_exam(request: ExamGenerationRequest = Body(...), user: dict = Depends(get_current_user)):
    logger.info("[ExamAPI] generate exam user=%s", user.get("email", "unknown"))
    _require_teacher(user, "Only teachers can generate exams")
    _require_document_access(user, request.file_ids)
    result = await exam_workflow_service.generate_exam_with_pdf(request)
    redis_cache.invalidate_namespaces(
        studio_cache.exam_list_namespace(),
        studio_cache.exam_detail_namespace(studio_cache.id_from_result(result, "exam_id", "id")),
    )
    return result


@router.post("/generate-questions-only")
async def generate_questions_only(request: ExamGenerationRequest = Body(...), user: dict = Depends(get_current_user)):
    logger.info("[ExamAPI] generate questions only user=%s", user.get("email", "unknown"))
    _require_teacher(user, "Only teachers can generate exams")
    _require_document_access(user, request.file_ids)
    result = await exam_workflow_service.generate_questions_only(request)
    redis_cache.invalidate_namespaces(
        studio_cache.exam_list_namespace(),
        studio_cache.exam_detail_namespace(studio_cache.id_from_result(result, "exam_id", "id")),
    )
    return result


@router.post("/{exam_id}/regenerate-pdf")
async def regenerate_pdf(exam_id: str, questions: list = Body(..., embed=True), exam_name: str = Body("Exam", embed=True), user: dict = Depends(get_current_user)):
    _require_teacher_exam_access(user, exam_id, "Only teachers can regenerate exam PDFs")
    logger.info("[ExamAPI] regenerate pdf exam_id=%s", exam_id)
    result = await exam_workflow_service.regenerate_exam_pdf(exam_id, questions, exam_name)
    redis_cache.invalidate_namespaces(studio_cache.exam_detail_namespace(exam_id))
    return result


@router.get("/{exam_id}/pdf")
async def download_exam_pdf(exam_id: str, user: dict = Depends(get_current_user)):
    _require_exam_access(user, exam_id)
    return exam_helpers.exam_pdf_response(PDF_DIR, exam_id)


@router.get("/{exam_id}/image/{image_name}")
async def get_exam_image(exam_id: str, image_name: str, user: dict = Depends(get_current_user)):
    _require_exam_access(user, exam_id)
    return exam_helpers.exam_image_response(IMAGES_DIR, exam_id, image_name)


@router.get("/difficulties")
async def get_exam_difficulties():
    return {
        "difficulties": [
            {
                "value": "easy",
                "label": "Easy",
                "description": "Focuses on recall and basic understanding.",
                "bloom_levels": ["remember", "understand"],
            },
            {
                "value": "medium",
                "label": "Medium",
                "description": "Balances understanding, application, and analysis.",
                "bloom_levels": ["understand", "apply", "analyze"],
            },
            {
                "value": "difficult",
                "label": "Difficult",
                "description": "Emphasizes analysis, evaluation, and creation.",
                "bloom_levels": ["analyze", "evaluate", "create"],
            },
        ]
    }


@router.get("/question-types")
async def get_question_types():
    return {
        "types": [
            {
                "value": "multiple_choice",
                "label": "Multiple Choice",
                "description": "Choose one correct answer.",
            }
        ]
    }


@router.get("/list")
async def get_exams_list(
    response: Response,
    class_id: str = Query(..., description="Class ID"),
    user: dict = Depends(get_current_user),
):
    require_allowed(can_access_class(user["user_id"], class_id))

    async def load():
        exams = await _run_exam_service(
            get_exams_by_class,
            class_id,
            user["user_id"],
            action="Get exams",
        )
        return {"message": "Fetched exams", "exams": exams, "total": len(exams)}

    result = await redis_cache.get_or_set_json_with_status(
        "exam:list",
        {"user_id": user["user_id"], "class_id": class_id},
        load,
        version_namespaces=[studio_cache.exam_list_namespace()],
    )
    redis_cache.set_response_cache_headers(response, result)
    return result.value


@router.get("/{exam_id}")
async def get_exam(
    exam_id: str,
    response: Response,
    include_answers: bool = Query(True, description="Include answers for teachers"),
    user: dict = Depends(get_current_user),
):
    is_teacher = is_user_teacher(user["user_id"])
    if not is_teacher:
        include_answers = False

    async def load():
        exam_payload = await _run_exam_service(
            get_exam_by_id,
            exam_id,
            user["user_id"],
            include_answers,
            action="Get exam",
        )
        return {"message": "Fetched exam", "exam": exam_payload}

    if not redis_cache.is_enabled() or not studio_cache.can_use_cache(can_access_exam, user["user_id"], exam_id):
        result = await redis_cache.load_without_cache("exam:detail", load, reason="disabled_or_access_check")
        redis_cache.set_response_cache_headers(response, result)
        return result.value

    result = await redis_cache.get_or_set_json_with_status(
        "exam:detail",
        {"user_id": user["user_id"], "exam_id": exam_id, "include_answers": include_answers},
        load,
        version_namespaces=[studio_cache.exam_detail_namespace(exam_id)],
    )
    redis_cache.set_response_cache_headers(response, result)
    return result.value


@router.put("/{exam_id}")
async def update_exam(exam_id: str, request: ExamUpdateRequest = Body(...), user: dict = Depends(get_current_user)):
    _require_teacher_exam_access(user, exam_id, "Only teachers can update exams")
    result = await _run_exam_service(
        update_exam_record,
        exam_id,
        user["user_id"],
        request.title,
        request.description,
        request.questions,
        request.difficulty,
        request.duration_minutes,
        request.file_ids,
        request.start_at,
        request.end_at,
        action="Update exam",
    )
    redis_cache.invalidate_namespaces(studio_cache.exam_list_namespace(), studio_cache.exam_detail_namespace(exam_id))
    return {"message": "Exam updated", "exam": result}


@router.delete("/{exam_id}")
async def delete_exam(exam_id: str, user: dict = Depends(get_current_user)):
    _require_teacher_exam_access(user, exam_id, "Only teachers can delete exams")
    result = await _run_exam_service(
        delete_exam_record,
        exam_id,
        user["user_id"],
        action="Delete exam",
    )
    redis_cache.invalidate_namespaces(studio_cache.exam_list_namespace(), studio_cache.exam_detail_namespace(exam_id))
    return result


@router.post("/{exam_id}/publish")
async def publish_exam(exam_id: str, is_published: bool = Body(True, embed=True), user: dict = Depends(get_current_user)):
    _require_teacher_exam_access(user, exam_id, "Only teachers can publish exams")
    result = await _run_exam_service(
        publish_exam_record,
        exam_id,
        user["user_id"],
        is_published,
        action="Publish exam",
    )
    redis_cache.invalidate_namespaces(studio_cache.exam_list_namespace(), studio_cache.exam_detail_namespace(exam_id))
    action = "published" if is_published else "unpublished"
    return {"message": f"Exam {action}", "exam": result}


@router.post("/{exam_id}/start", response_model=ExamStartResponse)
async def start_exam(exam_id: str, user: dict = Depends(get_current_user)):
    return await _run_exam_service(
        start_exam_submission,
        exam_id,
        user["user_id"],
        action="Start exam",
    )


@router.post("/submission/{submission_id}/submit")
async def submit_exam(submission_id: str, request: ExamSubmitRequest = Body(...), user: dict = Depends(get_current_user)):
    await run_service(require_submission_owner, user["user_id"], submission_id)
    result = await _run_exam_service(
        submit_exam_submission,
        submission_id,
        user["user_id"],
        request.answers,
        request.time_spent_seconds,
        action="Submit exam",
    )
    return {"message": "Exam submitted", "submission": result}


@router.get("/{exam_id}/my-submissions")
async def get_my_exam_submissions(exam_id: str, user: dict = Depends(get_current_user)):
    submissions = await _run_exam_service(
        get_student_exam_submissions,
        exam_id,
        user["user_id"],
        action="Get submissions",
    )
    return {"submissions": submissions, "total": len(submissions)}


@router.get("/{exam_id}/submissions")
async def get_exam_submissions(exam_id: str, user: dict = Depends(get_current_user)):
    _require_teacher_exam_access(user, exam_id, "Only teachers can view all submissions")
    submissions = await _run_exam_service(
        get_exam_submission_rows,
        exam_id,
        user["user_id"],
        action="Get submissions",
    )
    return {"submissions": submissions, "total": len(submissions)}


@router.put("/submission/{submission_id}/grade")
async def grade_submission(submission_id: str, request: GradeSubmissionRequest = Body(...), user: dict = Depends(get_current_user)):
    _require_teacher(user, "Only teachers can grade exams")
    await run_service(require_submission_teacher, user["user_id"], submission_id)
    answers_grades = exam_helpers.dump_grade_items(request.answers_grades)
    result = await _run_exam_service(
        grade_exam_submission,
        submission_id,
        user["user_id"],
        answers_grades,
        request.teacher_comment,
        action="Grade submission",
    )
    return {"message": "Submission graded", "submission": result}


@router.post("/submission/{submission_id}/ai-grade")
async def ai_grade_submission(submission_id: str, user: dict = Depends(get_current_user)):
    _require_teacher(user, "Only teachers can trigger AI grading")
    await run_service(require_submission_teacher, user["user_id"], submission_id)
    return await exam_workflow_service.ai_grade_submission(submission_id)

