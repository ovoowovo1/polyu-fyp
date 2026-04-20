# -*- coding: utf-8 -*-
"""
Exam Router - Multi-Agent 考試生成 API 端點
"""

from fastapi import APIRouter, HTTPException, Body, Depends, Query
from fastapi.responses import FileResponse
from typing import Optional, List
from pydantic import BaseModel, model_validator
import os
import asyncio

from app.agents.schemas import (
    ExamGenerationRequest,
    ExamGenerationResponse,
    ExamQuestion,
)
from app.agents.graph import run_exam_generation, run_exam_generation_with_pdf
from app.utils.jwt_utils import get_current_user
from app.services import pg_service
from app.services.ai_service import ai_grade_answer, ai_generate_exam_overall_comment
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/exam", tags=["exam"])


# ============== Pydantic Models ==============

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
    
    @model_validator(mode='after')
    def validate_identifiers(self):
        # 確保至少提供 answer_id 或 exam_question_id 其中之一
        if not self.answer_id and not self.exam_question_id:
            raise ValueError('必須提供 answer_id 或 exam_question_id 其中之一')
        return self


class GradeSubmissionRequest(BaseModel):
    answers_grades: Optional[List[GradeAnswerItem]] = None
    teacher_comment: Optional[str] = None

# PDF 和圖片目錄
PDF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "static",
    "pdfs"
)
IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "static",
    "images"
)


@router.post("/generate", response_model=ExamGenerationResponse)
async def generate_exam(
    request: ExamGenerationRequest = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    使用 Multi-Agent 系統生成考試
    
    流程：
    1. Retriever Agent - 從上傳的文件中檢索相關內容
    2. Generator Agent - 根據檢索內容生成題目
    3. Visualizer Agent - 為需要圖表的題目生成圖片
    4. Reviewer Agent - 審核題目品質，不通過則重新生成
    
    最終輸出包含題目列表和 PDF 路徑
    """
    logger.info(f"[ExamAPI] 收到考試生成請求 - 用戶: {user.get('email', 'unknown')}")
    logger.info(f"[ExamAPI] 請求參數 - 文件數: {len(request.file_ids)}, 題數: {request.num_questions}, 難度: {request.difficulty}")
    
    try:
        # 執行 Multi-Agent 工作流程（包含 PDF 生成）
        response = await run_exam_generation_with_pdf(request)
        
        logger.info(f"[ExamAPI] 考試生成完成 - ID: {response.exam_id}, 題數: {len(response.questions)}")
        
        return response
        
    except ValueError as e:
        logger.error(f"[ExamAPI] 參數錯誤: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 生成失敗: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"考試生成失敗: {str(e)}")


@router.post("/generate-questions-only")
async def generate_questions_only(
    request: ExamGenerationRequest = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    只生成題目，不生成 PDF
    適用於需要先預覽或編輯題目的情況
    """
    logger.info(f"[ExamAPI] 收到題目生成請求（不含 PDF）- 用戶: {user.get('email', 'unknown')}")
    
    try:
        response = await run_exam_generation(request)
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 生成失敗: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"題目生成失敗: {str(e)}")


@router.post("/{exam_id}/regenerate-pdf")
async def regenerate_pdf(
    exam_id: str,
    questions: list = Body(..., embed=True),
    exam_name: str = Body("考試", embed=True),
    user: dict = Depends(get_current_user)
):
    """
    根據提供的題目重新生成 PDF
    適用於用戶編輯題目後需要重新生成 PDF
    """
    from app.utils.pdf_generator import generate_exam_pdf
    from app.agents.schemas import ExamQuestion
    
    logger.info(f"[ExamAPI] 重新生成 PDF - 考試ID: {exam_id}")
    
    try:
        # 轉換題目格式
        exam_questions = [ExamQuestion(**q) if isinstance(q, dict) else q for q in questions]
        
        # 生成 PDF
        pdf_path = await generate_exam_pdf(
            exam_id=exam_id,
            exam_name=exam_name,
            questions=exam_questions,
        )
        
        return {
            "message": "PDF 重新生成成功",
            "exam_id": exam_id,
            "pdf_path": pdf_path
        }
        
    except Exception as e:
        logger.error(f"[ExamAPI] PDF 重新生成失敗: {e}")
        raise HTTPException(status_code=500, detail=f"PDF 生成失敗: {str(e)}")


@router.get("/{exam_id}/pdf")
async def download_exam_pdf(
    exam_id: str,
    user: dict = Depends(get_current_user)
):
    """
    下載考試 PDF
    """
    pdf_filename = f"{exam_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")
    
    return FileResponse(
        path=pdf_path,
        filename=pdf_filename,
        media_type="application/pdf"
    )


@router.get("/{exam_id}/image/{image_name}")
async def get_exam_image(
    exam_id: str,
    image_name: str,
):
    """
    獲取考試相關的圖片
    """
    # 安全性檢查：確保圖片名稱以考試 ID 開頭
    if not image_name.startswith(exam_id):
        raise HTTPException(status_code=403, detail="無權訪問此圖片")
    
    image_path = os.path.join(IMAGES_DIR, image_name)
    
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="圖片不存在")
    
    return FileResponse(
        path=image_path,
        media_type="image/png"
    )


@router.get("/difficulties")
async def get_exam_difficulties():
    """獲取可用的難度級別"""
    return {
        "difficulties": [
            {
                "value": "easy",
                "label": "簡單",
                "description": "記憶和理解層級的題目",
                "bloom_levels": ["remember", "understand"]
            },
            {
                "value": "medium",
                "label": "中等",
                "description": "理解、應用和分析層級的題目",
                "bloom_levels": ["understand", "apply", "analyze"]
            },
            {
                "value": "difficult",
                "label": "困難",
                "description": "分析、評估和創作層級的題目",
                "bloom_levels": ["analyze", "evaluate", "create"]
            }
        ]
    }


@router.get("/question-types")
async def get_question_types():
    """獲取支援的題目類型"""
    return {
        "types": [
            {
                "value": "multiple_choice",
                "label": "選擇題",
                "description": "四選一選擇題"
            },
            # 未來可擴展其他類型
            # {
            #     "value": "short_answer",
            #     "label": "簡答題",
            #     "description": "需要簡短文字回答"
            # },
        ]
    }


# ============== 考試管理 API ==============

@router.get("/list")
async def get_exams_list(
    class_id: str = Query(..., description="班級 ID"),
    user: dict = Depends(get_current_user)
):
    """
    獲取指定班級的考試列表
    """
    try:
        exams = await asyncio.to_thread(pg_service.get_exams_by_class, class_id)
        return {
            "message": "成功獲取考試列表",
            "exams": exams,
            "total": len(exams)
        }
    except Exception as e:
        logger.error(f"[ExamAPI] 獲取考試列表失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取考試列表失敗: {str(e)}")


@router.get("/{exam_id}")
async def get_exam(
    exam_id: str,
    include_answers: bool = Query(True, description="是否包含答案（學生作答時應設為 False）"),
    user: dict = Depends(get_current_user)
):
    """
    根據 ID 獲取考試詳情
    
    - 老師：可以看到完整題目和答案
    - 學生：只能看到已發布的考試，且如果 include_answers=False 則不顯示答案
    """
    try:
        # 檢查用戶角色
        is_teacher = pg_service.is_user_teacher(user["user_id"])
        
        # 學生不能看答案
        if not is_teacher:
            include_answers = False
        
        exam = await asyncio.to_thread(
            pg_service.get_exam_by_id,
            exam_id,
            user["user_id"],
            include_answers
        )
        return {
            "message": "成功獲取考試",
            "exam": exam
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="考試不存在")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 獲取考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取考試失敗: {str(e)}")


@router.put("/{exam_id}")
async def update_exam(
    exam_id: str,
    request: ExamUpdateRequest = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    更新考試（僅限老師）
    """
    # 檢查權限
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="只有老師可以更新考試")
    
    try:
        result = await asyncio.to_thread(
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
        )
        return {
            "message": "考試已更新",
            "exam": result
        }
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="考試不存在")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 更新考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"更新考試失敗: {str(e)}")


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: str,
    user: dict = Depends(get_current_user)
):
    """
    刪除考試（僅限老師）
    """
    # 檢查權限
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="只有老師可以刪除考試")
    
    try:
        result = await asyncio.to_thread(pg_service.delete_exam, exam_id)
        return result
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="考試不存在")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 刪除考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"刪除考試失敗: {str(e)}")


@router.post("/{exam_id}/publish")
async def publish_exam(
    exam_id: str,
    is_published: bool = Body(True, embed=True),
    user: dict = Depends(get_current_user)
):
    """
    發布或取消發布考試（僅限老師）
    發布後學生才能看到並開始作答
    """
    # 檢查權限
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="只有老師可以發布考試")
    
    try:
        result = await asyncio.to_thread(pg_service.publish_exam, exam_id, is_published)
        action = "發布" if is_published else "取消發布"
        return {
            "message": f"考試已{action}",
            "exam": result
        }
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="考試不存在")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 發布考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"發布考試失敗: {str(e)}")


# ============== 學生作答 API ==============

@router.post("/{exam_id}/start", response_model=ExamStartResponse)
async def start_exam(
    exam_id: str,
    user: dict = Depends(get_current_user)
):
    """
    學生開始作答考試
    會建立一筆新的提交記錄，狀態為 in_progress
    """
    try:
        result = await asyncio.to_thread(
            pg_service.start_exam_submission,
            exam_id,
            user["user_id"]
        )
        return result
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="考試不存在")
        if "尚未發布" in str(e):
            raise HTTPException(status_code=403, detail="The exam has not yet been released.")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 開始考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"開始考試失敗: {str(e)}")


@router.post("/submission/{submission_id}/submit")
async def submit_exam(
    submission_id: str,
    request: ExamSubmitRequest = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    學生提交考試答案
    選擇題會自動批改計分
    """
    try:
        result = await asyncio.to_thread(
            pg_service.submit_exam,
            submission_id,
            request.answers,
            request.time_spent_seconds,
        )
        return {
            "message": "考試已提交",
            "submission": result
        }
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="提交記錄不存在")
        if "已完成" in str(e):
            raise HTTPException(status_code=400, detail="此提交已完成，無法再次提交")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 提交考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"提交考試失敗: {str(e)}")


@router.get("/{exam_id}/my-submissions")
async def get_my_exam_submissions(
    exam_id: str,
    user: dict = Depends(get_current_user)
):
    """
    學生查看自己在特定考試的所有提交記錄
    """
    try:
        submissions = await asyncio.to_thread(
            pg_service.get_student_exam_submissions,
            exam_id,
            user["user_id"]
        )
        return {
            "submissions": submissions,
            "total": len(submissions)
        }
    except Exception as e:
        logger.error(f"[ExamAPI] 獲取提交記錄失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取提交記錄失敗: {str(e)}")


# ============== 老師批改 API ==============

@router.get("/{exam_id}/submissions")
async def get_exam_submissions(
    exam_id: str,
    user: dict = Depends(get_current_user)
):
    """
    獲取考試的所有提交記錄（僅限老師）
    """
    # 檢查權限
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="只有老師可以查看所有提交記錄")
    
    try:
        submissions = await asyncio.to_thread(pg_service.get_exam_submissions, exam_id)
        return {
            "submissions": submissions,
            "total": len(submissions)
        }
    except Exception as e:
        logger.error(f"[ExamAPI] 獲取提交記錄失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取提交記錄失敗: {str(e)}")


@router.put("/submission/{submission_id}/grade")
async def grade_submission(
    submission_id: str,
    request: GradeSubmissionRequest = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    老師批改考試提交
    
    可以為每題評分並給予回饋，以及整體評語
    """
    # 檢查權限
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="只有老師可以批改考試")
    
    try:
        # 轉換 Pydantic 模型為 dict
        answers_grades = None
        if request.answers_grades:
            answers_grades = [g.model_dump() for g in request.answers_grades]
        
        result = await asyncio.to_thread(
            pg_service.grade_exam_submission,
            submission_id,
            user["user_id"],
            answers_grades,
            request.teacher_comment,
        )
        return {
            "message": "批改完成",
            "submission": result
        }
    except RuntimeError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail="提交記錄不存在")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[ExamAPI] 批改考試失敗: {e}")
        raise HTTPException(status_code=500, detail=f"批改考試失敗: {str(e)}")


@router.post("/submission/{submission_id}/ai-grade")
async def ai_grade_submission(
    submission_id: str,
    user: dict = Depends(get_current_user)
):
    """
    AI automatic grading for exam submission.
    
    - Multiple choice questions: Uses existing auto-grading logic (already graded on submit)
    - Short answer/essay/calculation: Uses Gemini AI to grade with structured output
    
    Returns grading results that teacher can review and override.
    """
    # Check permission - only teachers can trigger AI grading
    if not pg_service.is_user_teacher(user["user_id"]):
        raise HTTPException(status_code=403, detail="Only teachers can trigger AI grading")
    
    try:
        # Get submission with answers
        submission = await asyncio.to_thread(
            pg_service.get_submission_with_answers,
            submission_id
        )
        
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        answers = submission.get("answers", [])
        if not answers:
            raise HTTPException(status_code=400, detail="No answers found in submission")
        
        # Separate MCQ (already graded) and non-MCQ questions
        ai_grading_tasks = []
        answer_indices = []  # Track which answers need AI grading
        
        for idx, answer in enumerate(answers):
            q = answer.get("question_snapshot", {})
            question_type = q.get("question_type", "")
            choices = q.get("choices", [])
            
            # Determine if this is truly a multiple choice question
            # A real MCQ must have question_type == "multiple_choice" AND have actual choices
            is_real_mcq = question_type == "multiple_choice" and choices and len(choices) > 0
            
            # Skip real multiple choice - already auto-graded on submission
            if is_real_mcq:
                continue
            
            # For all other questions (short_answer, essay, calculation, or
            # questions incorrectly tagged as MC but have no choices) - use AI grading
            # Determine the effective question type for AI grading
            effective_type = question_type
            if question_type == "multiple_choice" and (not choices or len(choices) == 0):
                # This is likely a short answer question incorrectly tagged as MC
                effective_type = "short_answer"
            
            task = ai_grade_answer(
                question_text=q.get("question_text", q.get("question", "")),
                question_type=effective_type,
                model_answer=q.get("model_answer"),
                marking_scheme=q.get("marking_scheme", []),
                student_answer=answer.get("answer_text", ""),
                max_marks=q.get("marks", 1)
            )
            ai_grading_tasks.append(task)
            answer_indices.append(idx)
        
        # Run all AI grading tasks in parallel
        ai_results = []
        if ai_grading_tasks:
            ai_results = await asyncio.gather(*ai_grading_tasks, return_exceptions=True)
        
        # Build grading data for each answer
        graded_answers = []
        ai_grading_idx = 0
        
        for idx, answer in enumerate(answers):
            q = answer.get("question_snapshot", {})
            question_type = q.get("question_type", "")
            
            grade_item = {
                "answer_id": answer.get("id"),
                "exam_question_id": answer.get("exam_question_id"),
                "marks_earned": answer.get("marks_earned", 0),
                "teacher_feedback": answer.get("teacher_feedback", ""),
                "is_correct": answer.get("is_correct", False),
                "ai_graded": False
            }
            
            # If this was an AI-graded answer, update with AI results
            if idx in answer_indices:
                ai_result = ai_results[ai_grading_idx]
                ai_grading_idx += 1
                
                if isinstance(ai_result, Exception):
                    logger.error(f"AI grading failed for answer {answer.get('id')}: {ai_result}")
                    grade_item["teacher_feedback"] = f"AI grading failed: {str(ai_result)}. Please grade manually."
                else:
                    grade_item["marks_earned"] = ai_result.get("marks_earned", 0)
                    grade_item["teacher_feedback"] = ai_result.get("feedback", "")
                    grade_item["is_correct"] = ai_result.get("is_correct", False)
                    grade_item["ai_graded"] = True
            
            graded_answers.append(grade_item)
        
        # Calculate totals for overall comment
        total_score = sum(g["marks_earned"] for g in graded_answers)
        total_marks = sum(a.get("question_snapshot", {}).get("marks", 1) for a in answers)
        
        # Generate summary for AI
        summary_lines = []
        for i, g in enumerate(graded_answers):
            ans = answers[i]
            q_text = ans.get("question_snapshot", {}).get("question_text", "")
            if q_text:
                q_text = q_text[:50]
            else:
                q_text = "Question"
                
            marks = g["marks_earned"]
            max_m = ans.get("question_snapshot", {}).get("marks", 1)
            is_corr = g["is_correct"]
            summary_lines.append(f"Q{i+1}: {q_text}... | Score: {marks}/{max_m} | Correct: {is_corr}")
            
        submission_summary = "\n".join(summary_lines)
        
        # Generate overall comment
        overall_comment = await ai_generate_exam_overall_comment(
            submission_summary=submission_summary,
            total_score=total_score,
            total_marks=total_marks
        )
        
        # Save AI grading results to database
        result = await asyncio.to_thread(
            pg_service.ai_grade_exam_submission,
            submission_id,
            graded_answers,
            teacher_comment=overall_comment
        )
        
        return {
            "message": "AI grading completed",
            "submission": result,
            "graded_answers": graded_answers
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExamAPI] AI grading failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI grading failed: {str(e)}")

