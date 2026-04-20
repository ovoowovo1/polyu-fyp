from fastapi import APIRouter, HTTPException, Form, Query, Body, Depends
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel
import json
import asyncio

import app.logger 

from app.logger import get_logger

logger = get_logger(__name__)

from app.utils.aqg import (
    MultipleChoice,
    BloomLevel,
    Difficulty,
    maybe_truncate_or_summarize,
    distribute_counts,
    build_prompt,
    DIFFICULTY_TO_BLOOM,
    _MC,
    _QuizWithName
)
from app.utils.api_key_manager import with_gemini_retry_async, get_genai_client
from app.utils.openai_response import extract_chat_completion_text
from app.config import get_settings
from app.services import pg_service
from app.services.ai_service import generate_quiz_feedback_text
from app.utils.jwt_utils import get_current_user

router = APIRouter(prefix="", tags=["quiz"])


class QuizGenerateResponse(BaseModel):
    questions: List[MultipleChoice]
    source_text_length: int
    was_summarized: bool


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(
    file_ids: List[str] = Form(...),
    bloom_levels: Optional[List[BloomLevel]] = Form(None),
    difficulty: Optional[Difficulty] = Form(None),
    num_questions: int = Form(5),
):
    """
    從 Neo4j 文件生成測驗題目
    
    參數:
    - file_ids: Neo4j 文件 ID 列表（必填）
    - bloom_levels: Bloom 認知層級列表（可選）
    - difficulty: 難度級別 (easy/medium/difficult)（可選）
    - num_questions: 要生成的題目數量（默認 5，範圍 1-50）
    """
    logger.debug(f"[Quiz] 接收到的參數 - file_ids: {file_ids}, bloom_levels: {bloom_levels}, difficulty: {difficulty}, num_questions: {num_questions}")
    logger.debug(f"[Quiz] difficulty 類型: {type(difficulty)}, 值: {repr(difficulty)}")
    try:
        # 驗證輸入
        if not file_ids or len(file_ids) == 0:
            raise HTTPException(status_code=400, detail="必須提供至少一個文件 ID")
        
        # 處理 Bloom 層級選擇
        selected_levels: List[BloomLevel] = []
        if bloom_levels:
            # 去重並保持順序
            selected_levels = list(dict.fromkeys(bloom_levels))
        
        if difficulty:
            mapped = DIFFICULTY_TO_BLOOM[difficulty]
            if selected_levels:
                # 合併：保持現有順序，然後添加 mapped 中的新層級
                for lvl in mapped:
                    if lvl not in selected_levels:
                        selected_levels.append(lvl)
            else:
                selected_levels = mapped.copy()
        
        if not selected_levels:
            # 默認使用 easy 難度
            selected_levels = DIFFICULTY_TO_BLOOM["easy"].copy()
        
        # 從 Neo4j 獲取文件內容
        try:
            source_text = await asyncio.to_thread(pg_service.get_files_text_content, file_ids)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"獲取文件內容失敗: {str(e)}")
        
        # 確保有文本內容
        if not source_text or not source_text.strip():
            raise HTTPException(status_code=400, detail="文件沒有可用的文本內容")
        
        # 獲取 class_id（所有文件必須屬於同一個班級）
        try:
            from app.services.pg_db import _get_conn
            with _get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT DISTINCT class_id FROM documents WHERE id = ANY(%s::uuid[])", (file_ids,))
                rows = cur.fetchall()
                if len(rows) != 1 or not rows[0]["class_id"]:
                    raise HTTPException(status_code=400, detail="所有文件必須屬於同一個班級")
                class_id = str(rows[0]["class_id"])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"獲取班級信息失敗: {str(e)}")
        
        # 驗證題目數量
        if num_questions < 1 or num_questions >= 100:
            raise HTTPException(status_code=400, detail="題目數量必須在 1-100 之間")
        
        settings = get_settings()
        model_name = settings.google_ai_model or "gemini-2.5-flash"
        
        # 準備數據（這部分不需要 API key）
        original_length = len(source_text)
        level_counts = distribute_counts(num_questions, selected_levels)
        
        # 第一步：處理長文本（可能需要摘要）
        processed_text = None
        was_summarized = False
        
        if len(source_text) > 12000:  # MAX_SOURCE_CHARS
            async def _summarize_text(api_key: str, source_text: str, model_name: str):
                client = get_genai_client(api_key)
                return await asyncio.to_thread(
                    maybe_truncate_or_summarize, client, model_name, source_text
                )
            
            processed_text = await with_gemini_retry_async(
                "摘要生成",
                _summarize_text,
                source_text,
                model_name,
                error_type=HTTPException
            )
            was_summarized = True
        else:
            processed_text = source_text
            was_summarized = False
        
        # 構建提示詞
        prompt = build_prompt(processed_text, level_counts)
        
        # 第二步：生成題目（使用統一的重試機制）
        async def _generate_quiz(api_key: str, prompt: str, model_name: str):
            client = get_genai_client(api_key)
            logger.info(f"[Quiz] 正在生成題目和測驗名稱...")
            
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "quiz_generation",
                        "strict": True,
                        "schema": _QuizWithName.model_json_schema()
                    }
                }
            )
            
            # 解析響應
            raw_text = extract_chat_completion_text(response, "Quiz 生成")
            if not raw_text:
                raise RuntimeError("API 返回空響應")
            
            # 解析 JSON 並驗證
            quiz_with_name_data = json.loads(raw_text)
            quiz_name = quiz_with_name_data.get("quiz_name", None)
            questions_data = quiz_with_name_data.get("questions", [])
            questions = [MultipleChoice(**q) for q in questions_data]
            
            logger.info(f"[Quiz] 生成成功 - 名稱: {quiz_name}, 題目: {len(questions)} 題")
            return {"quiz_name": quiz_name, "questions": questions}
        
        try:
            result = await with_gemini_retry_async(
                "題目生成",
                _generate_quiz,
                prompt,
                model_name,
                error_type=HTTPException
            )
            quiz_name = result["quiz_name"]
            questions = result["questions"]
        except json.JSONDecodeError as err:
            # JSON 解析錯誤通常不是 API 限制問題，直接拋出
            raise HTTPException(status_code=500, detail=f"解析 Gemini 響應失敗: {str(err)}")
        
        # 準備響應數據
        quiz_response = QuizGenerateResponse(
            questions=questions,
            source_text_length=len(processed_text),
            was_summarized=was_summarized
        )
        
        # 保存測驗到 Neo4j（包含 AI 生成的名稱）
        try:
            # 將 Pydantic 模型轉換為字典以便保存
            quiz_data = {
                "questions": [q.model_dump() for q in questions],
                "source_text_length": len(processed_text),
                "was_summarized": was_summarized,
            }

            saved_info = await asyncio.to_thread(
                pg_service.save_quiz, quiz_data, file_ids, quiz_name, class_id
            )
            logger.info(f"[Quiz] 測驗已保存到 Neo4j，ID: {saved_info['quiz_id']}, 名稱: {saved_info.get('name', 'N/A')}")
        except Exception as save_err:
            logger.error(f"[Quiz] 保存測驗到 Neo4j 失敗: {save_err}")
            # 不拋出錯誤，繼續返回測驗結果
        
        return quiz_response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成測驗失敗: {str(e)}")


@router.get("/bloom-levels")
async def get_bloom_levels():
    """獲取所有可用的 Bloom 層級"""
    from app.utils.aqg import BLOOM_DESCRIPTIONS
    
    return {
        "levels": [
            {"value": level, "description": desc}
            for level, desc in BLOOM_DESCRIPTIONS.items()
        ]
    }


@router.get("/difficulties")
async def get_difficulties():
    """獲取所有難度級別及其對應的 Bloom 層級"""
    return {
        "difficulties": [
            {"value": diff, "bloom_levels": levels}
            for diff, levels in DIFFICULTY_TO_BLOOM.items()
        ]
    }


@router.get("/list")
async def get_all_quizzes(class_id: str = Query(...)):
    """獲取特定班級的所有測驗列表"""
    try:
        quizzes = await asyncio.to_thread(pg_service.get_quizzes_by_class, class_id)
        return {
            "message": "成功獲取測驗列表",
            "quizzes": quizzes,
            "total": len(quizzes)
        }
    except Exception as e:
        logger.error(f"獲取測驗列表失敗: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取測驗列表失敗: {str(e)}")


@router.get("/{quiz_id}")
async def get_quiz(quiz_id: str):
    """根據 ID 獲取特定測驗"""
    try:
        quiz = await asyncio.to_thread(pg_service.get_quiz_by_id, quiz_id)
        return {
            "message": "成功獲取測驗",
            "quiz": quiz
        }
    except Exception as e:
        if "測驗不存在" in str(e):
            raise HTTPException(status_code=404, detail="測驗不存在")
        raise HTTPException(status_code=500, detail=f"獲取測驗失敗: {str(e)}")


@router.post("/")
async def create_quiz(payload: dict = Body(...)):
    """Create a quiz manually (teacher). Expects JSON with keys: questions (list), name (optional), file_ids (optional list), class_id (optional)."""
    try:
        questions = payload.get("questions") or []
        if not isinstance(questions, list) or len(questions) == 0:
            raise HTTPException(status_code=400, detail="questions must be a non-empty list")

        file_ids = payload.get("file_ids") or []
        name = payload.get("name")
        class_id = payload.get("class_id")

        quiz_data = {"questions": questions}
        saved = await asyncio.to_thread(pg_service.save_quiz, quiz_data, file_ids, name, class_id)
        return {"message": "測驗已建立", "quiz": saved}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"建立測驗失敗: {e}")
        raise HTTPException(status_code=500, detail=f"建立測驗失敗: {str(e)}")


@router.put("/{quiz_id}")
async def update_quiz(quiz_id: str, payload: dict = Body(...)):
    """Update an existing quiz. Payload: questions (list), name (optional), file_ids (optional list)"""
    try:
        questions = payload.get("questions")
        if questions is None:
            raise HTTPException(status_code=400, detail="questions is required")

        name = payload.get("name")
        file_ids = payload.get("file_ids") if "file_ids" in payload else None

        quiz_data = {"questions": questions}
        updated = await asyncio.to_thread(pg_service.update_quiz, quiz_id, quiz_data, name, file_ids)
        return {"message": "測驗已更新", "quiz": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新測驗失敗: {e}")
        if "測驗不存在" in str(e):
            raise HTTPException(status_code=404, detail="測驗不存在")
        raise HTTPException(status_code=500, detail=f"更新測驗失敗: {str(e)}")


@router.delete("/{quiz_id}")
async def delete_quiz(quiz_id: str):
    """刪除測驗"""
    try:
        result = await asyncio.to_thread(pg_service.delete_quiz, quiz_id)
        return result
    except Exception as e:
        if "測驗不存在" in str(e):
            raise HTTPException(status_code=404, detail="測驗不存在")
        raise HTTPException(status_code=500, detail=f"刪除測驗失敗: {str(e)}")


@router.post("/{quiz_id}/submit")
async def submit_quiz(
    quiz_id: str, 
    payload: dict = Body(...), 
    user: dict = Depends(get_current_user)
):
    """
    Submit quiz answers.
    Payload: {
        "answers": [{"question_index": 0, "answer_index": 1, ...}],
        "score": 80,
        "total_questions": 5
    }
    """
    student_id = user["user_id"]
    answers = payload.get("answers", [])
    score = payload.get("score")
    total = payload.get("total_questions")
    
    if score is None or total is None:
         raise HTTPException(status_code=400, detail="Score and total_questions required")

    try:
        result = await asyncio.to_thread(
            pg_service.submit_quiz_result, 
            quiz_id, student_id, answers, score, total
        )
        return result
    except Exception as e:
        logger.error(f"Submit quiz failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Get all submissions for a quiz (Teacher only).
    """
    try:
        # Check if user is teacher
        if not pg_service.is_user_teacher(user["user_id"]):
             raise HTTPException(status_code=403, detail="Only teachers can view all results")
             
        results = await asyncio.to_thread(pg_service.get_quiz_submissions, quiz_id)
        return {"results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get quiz results failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{quiz_id}/my-result")
async def get_my_quiz_result(
    quiz_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Get my submission for a quiz (Student).
    """
    try:
        result = await asyncio.to_thread(
            pg_service.get_student_quiz_submission, 
            quiz_id, user["user_id"]
        )
        if not result:
            return {"submission": None}
        return {"submission": result}
    except Exception as e:
        logger.error(f"Get my result failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{quiz_id}/feedback")
async def generate_quiz_feedback(
    quiz_id: str,
    payload: dict = Body(...),
    user: dict = Depends(get_current_user)
):
    """
    生成 AI 測驗回饋，payload 期待:
    {
        "quiz_name": str,
        "score": int,
        "total_questions": int,
        "percentage": int,
        "bloom_summary": [{"level": "remember", "correct": 2, "total": 3, "accuracy": 67}, ...],
        "questions": [
            {
                "question": str,
                "choices": [str],
                "correct_answer_index": int,
                "user_answer_index": int | null,
                "bloom_level": str,
                "rationale": str
            },
            ...
        ]
    }
    """
    quiz_name = payload.get("quiz_name") or "Quiz"
    score = payload.get("score")
    total = payload.get("total_questions")
    percentage = payload.get("percentage")
    bloom_summary = payload.get("bloom_summary") or []
    questions = payload.get("questions") or []

    if score is None or total is None:
        raise HTTPException(status_code=400, detail="score and total_questions are required")

    try:
        feedback_text = await generate_quiz_feedback_text(
            quiz_name=quiz_name,
            score=score,
            total=total,
            percentage=percentage,
            bloom_summary=bloom_summary,
            questions=questions,
        )
        return {"feedback": feedback_text}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Generate feedback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
