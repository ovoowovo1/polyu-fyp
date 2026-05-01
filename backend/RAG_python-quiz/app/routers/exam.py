import os
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from app.agents.schemas import ExamGenerationRequest, ExamGenerationResponse
from app.logger import get_logger
from app.routers.service_helpers import require_teacher, run_service
from app.services import exam_workflow_service
from app.services import pg_service
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

@router.post("/generate", response_model=ExamGenerationResponse)
async def generate_exam(request: ExamGenerationRequest = Body(...), user: dict = Depends(get_current_user)):
    logger.info("[ExamAPI] generate exam user=%s", user.get("email", "unknown"))
    return await exam_workflow_service.generate_exam_with_pdf(request)


@router.post("/generate-questions-only")
async def generate_questions_only(request: ExamGenerationRequest = Body(...), user: dict = Depends(get_current_user)):
    logger.info("[ExamAPI] generate questions only user=%s", user.get("email", "unknown"))
    return await exam_workflow_service.generate_questions_only(request)


@router.post("/{exam_id}/regenerate-pdf")
async def regenerate_pdf(exam_id: str, questions: list = Body(..., embed=True), exam_name: str = Body("Exam", embed=True), user: dict = Depends(get_current_user)):
    del user
    logger.info("[ExamAPI] regenerate pdf exam_id=%s", exam_id)
    return await exam_workflow_service.regenerate_exam_pdf(exam_id, questions, exam_name)


@router.get("/{exam_id}/pdf")
async def download_exam_pdf(exam_id: str, user: dict = Depends(get_current_user)):
    del user
    pdf_filename = f"{exam_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path=pdf_path, filename=pdf_filename, media_type="application/pdf")


@router.get("/{exam_id}/image/{image_name}")
async def get_exam_image(exam_id: str, image_name: str):
    if not image_name.startswith(exam_id):
        raise HTTPException(status_code=403, detail="Image does not belong to this exam")
    image_path = os.path.join(IMAGES_DIR, image_name)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path=image_path, media_type="image/png")


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
async def get_exams_list(class_id: str = Query(..., description="Class ID"), user: dict = Depends(get_current_user)):
    del user
    exams = await run_service(
        pg_service.get_exams_by_class,
        class_id,
        logger=logger,
        log_message="[ExamAPI] get exams failed: %s",
        fallback_detail=lambda error: f"Get exams failed: {error}",
    )
    return {"message": "Fetched exams", "exams": exams, "total": len(exams)}


@router.get("/{exam_id}")
async def get_exam(exam_id: str, include_answers: bool = Query(True, description="Include answers for teachers"), user: dict = Depends(get_current_user)):
    is_teacher = pg_service.is_user_teacher(user["user_id"])
    if not is_teacher:
        include_answers = False
    exam_payload = await run_service(
        pg_service.get_exam_by_id,
        exam_id,
        user["user_id"],
        include_answers,
        logger=logger,
        log_message="[ExamAPI] get exam failed: %s",
        fallback_detail=lambda error: f"Get exam failed: {error}",
    )
    return {"message": "Fetched exam", "exam": exam_payload}


@router.put("/{exam_id}")
async def update_exam(exam_id: str, request: ExamUpdateRequest = Body(...), user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can update exams", pg_service.is_user_teacher)
    result = await run_service(
        pg_service.update_exam,
        exam_id,
        request.title,
        request.description,
        request.questions,
        request.difficulty,
        request.duration_minutes,
        request.file_ids,
        request.start_at,
        request.end_at,
        logger=logger,
        log_message="[ExamAPI] update exam failed: %s",
        fallback_detail=lambda error: f"Update exam failed: {error}",
    )
    return {"message": "Exam updated", "exam": result}


@router.delete("/{exam_id}")
async def delete_exam(exam_id: str, user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can delete exams", pg_service.is_user_teacher)
    return await run_service(
        pg_service.delete_exam,
        exam_id,
        logger=logger,
        log_message="[ExamAPI] delete exam failed: %s",
        fallback_detail=lambda error: f"Delete exam failed: {error}",
    )


@router.post("/{exam_id}/publish")
async def publish_exam(exam_id: str, is_published: bool = Body(True, embed=True), user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can publish exams", pg_service.is_user_teacher)
    result = await run_service(
        pg_service.publish_exam,
        exam_id,
        is_published,
        logger=logger,
        log_message="[ExamAPI] publish exam failed: %s",
        fallback_detail=lambda error: f"Publish exam failed: {error}",
    )
    action = "published" if is_published else "unpublished"
    return {"message": f"Exam {action}", "exam": result}


@router.post("/{exam_id}/start", response_model=ExamStartResponse)
async def start_exam(exam_id: str, user: dict = Depends(get_current_user)):
    return await run_service(
        pg_service.start_exam_submission,
        exam_id,
        user["user_id"],
        logger=logger,
        log_message="[ExamAPI] start exam failed: %s",
        fallback_detail=lambda error: f"Start exam failed: {error}",
    )


@router.post("/submission/{submission_id}/submit")
async def submit_exam(submission_id: str, request: ExamSubmitRequest = Body(...), user: dict = Depends(get_current_user)):
    del user
    result = await run_service(
        pg_service.submit_exam,
        submission_id,
        request.answers,
        request.time_spent_seconds,
        logger=logger,
        log_message="[ExamAPI] submit exam failed: %s",
        fallback_detail=lambda error: f"Submit exam failed: {error}",
    )
    return {"message": "Exam submitted", "submission": result}


@router.get("/{exam_id}/my-submissions")
async def get_my_exam_submissions(exam_id: str, user: dict = Depends(get_current_user)):
    submissions = await run_service(
        pg_service.get_student_exam_submissions,
        exam_id,
        user["user_id"],
        logger=logger,
        log_message="[ExamAPI] get my submissions failed: %s",
        fallback_detail=lambda error: f"Get submissions failed: {error}",
    )
    return {"submissions": submissions, "total": len(submissions)}


@router.get("/{exam_id}/submissions")
async def get_exam_submissions(exam_id: str, user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can view all submissions", pg_service.is_user_teacher)
    submissions = await run_service(
        pg_service.get_exam_submissions,
        exam_id,
        logger=logger,
        log_message="[ExamAPI] get submissions failed: %s",
        fallback_detail=lambda error: f"Get submissions failed: {error}",
    )
    return {"submissions": submissions, "total": len(submissions)}


@router.put("/submission/{submission_id}/grade")
async def grade_submission(submission_id: str, request: GradeSubmissionRequest = Body(...), user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can grade exams", pg_service.is_user_teacher)
    answers_grades = [grade.model_dump() for grade in request.answers_grades] if request.answers_grades else None
    result = await run_service(
        pg_service.grade_exam_submission,
        submission_id,
        user["user_id"],
        answers_grades,
        request.teacher_comment,
        logger=logger,
        log_message="[ExamAPI] grade submission failed: %s",
        fallback_detail=lambda error: f"Grade submission failed: {error}",
    )
    return {"message": "Submission graded", "submission": result}


@router.post("/submission/{submission_id}/ai-grade")
async def ai_grade_submission(submission_id: str, user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can trigger AI grading", pg_service.is_user_teacher)
    return await exam_workflow_service.ai_grade_submission(submission_id)

