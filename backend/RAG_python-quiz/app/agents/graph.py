# -*- coding: utf-8 -*-
"""
LangGraph Main Flow - 考試生成工作流程
"""

from typing import Dict, Any, List, Optional
import uuid
import asyncio

from langgraph.graph import StateGraph, END

from app.agents.state import ExamGenerationState
from app.agents.nodes.retriever import retriever_node
from app.agents.nodes.generator import generator_node
from app.agents.nodes.visualizer import visualizer_node
from app.agents.nodes.reviewer import reviewer_node
from app.agents.schemas import ExamQuestion, ExamGenerationRequest, ExamGenerationResponse
from app.services import pg_service
from app.logger import get_logger

logger = get_logger(__name__)


def should_retry(state: ExamGenerationState) -> str:
    """
    決定是否需要重試
    
    Returns:
        "generator" - 需要重新生成題目 (REWRITE)
        "retriever" - 需要補充檢索 (RESEARCH)
        "pdf" - 通過審核，生成 PDF (PASS)
    """
    is_complete = state.get("is_complete", False)
    research_goal = state.get("research_goal")
    
    if is_complete:
        return "pdf"
    
    # 如果有 research_goal，則回到 retriever
    if research_goal:
        return "retriever"
        
    return "generator"


def create_exam_graph() -> StateGraph:
    """
    建立考試生成的 LangGraph 工作流程
    
    流程:
        START -> Retriever -> Generator -> Visualizer -> Reviewer
                                ^           ^               |
                                |           |_______________|
                                |           |   (Rewrite)   |
                                |___________|_______________|
                                        (Research)
        
        Reviewer -> END (if passed or max retries)
    """
    
    # 創建 StateGraph
    workflow = StateGraph(ExamGenerationState)
    
    # 添加節點
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("generator", generator_node)
    workflow.add_node("visualizer", visualizer_node)
    workflow.add_node("reviewer", reviewer_node)
    
    # 設置入口點
    workflow.set_entry_point("retriever")
    
    # 添加邊
    workflow.add_edge("retriever", "generator")
    workflow.add_edge("generator", "visualizer")
    workflow.add_edge("visualizer", "reviewer")
    
    # 條件邊：根據審核結果決定下一步
    workflow.add_conditional_edges(
        "reviewer",
        should_retry,
        {
            "generator": "generator",  # 重試生成
            "retriever": "retriever",  # 補充檢索
            "pdf": END  # 完成
        }
    )
    
    return workflow.compile()


async def run_exam_generation(
    request: ExamGenerationRequest
) -> ExamGenerationResponse:
    """
    執行考試生成流程
    
    Args:
        request: 考試生成請求
    
    Returns:
        ExamGenerationResponse: 生成結果
    """
    # 處理題型配置
    question_types = None
    if request.question_types:
        question_types = {
            "multiple_choice": request.question_types.multiple_choice,
            "short_answer": request.question_types.short_answer,
            "essay": request.question_types.essay,
        }
        total_questions = sum(question_types.values())
        logger.info(f"[ExamGraph] 開始考試生成 - 文件數: {len(request.file_ids)}, 題型配置: {question_types}")
    else:
        total_questions = request.num_questions
        logger.info(f"[ExamGraph] 開始考試生成 - 文件數: {len(request.file_ids)}, 題數: {request.num_questions}")
    
    # 初始化狀態
    initial_state: ExamGenerationState = {
        "file_ids": request.file_ids,
        "topic": request.topic or "",
        "difficulty": request.difficulty,
        "num_questions": request.num_questions,
        "question_types": question_types,  # 題型配置
        "custom_prompt": request.custom_prompt or "",  # 用戶自定義需求
        "context": "",
        "context_chunks": [],
        "questions": [],
        "images": {},
        "review_result": None,
        "feedback": "",
        "retry_count": 0,
        "max_retries": 3,
        "exam_name": request.exam_name or "",
        # 資料庫 exams.id 為 UUID，直接使用 uuid4，避免非 UUID 字串導致插入失敗
        "exam_id": str(uuid.uuid4()),
        "pdf_path": None,
        "warnings": [],
        "is_complete": False,
    }
    
    # 編譯並執行工作流程
    graph = create_exam_graph()
    
    # 執行工作流程
    final_state = await graph.ainvoke(initial_state)
    
    logger.info(f"[ExamGraph] 工作流程完成 - 考試ID: {final_state['exam_id']}")
    
    # 構建響應
    questions = final_state.get("questions", [])
    review_result = final_state.get("review_result")
    
    response = ExamGenerationResponse(
        exam_id=final_state["exam_id"],
        exam_name=final_state.get("exam_name", "考試"),
        questions=questions,
        pdf_path=final_state.get("pdf_path"),
        warnings=final_state.get("warnings", []),
        review_score=review_result.overall_score if review_result else 0
    )
    
    return response


async def run_exam_generation_with_pdf(
    request: ExamGenerationRequest
) -> ExamGenerationResponse:
    """
    執行考試生成流程並生成 PDF，然後保存到資料庫
    
    Args:
        request: 考試生成請求
    
    Returns:
        ExamGenerationResponse: 生成結果（包含 PDF 路徑）
    """
    # 先執行基本生成流程
    response = await run_exam_generation(request)
    
    # 如果有題目，生成 PDF
    if response.questions:
        try:
            from app.utils.pdf_generator import generate_exam_pdf
            
            pdf_path = await generate_exam_pdf(
                exam_id=response.exam_id,
                exam_name=response.exam_name,
                questions=response.questions,
            )
            
            response.pdf_path = pdf_path
            logger.info(f"[ExamGraph] PDF 生成完成: {pdf_path}")
            
        except Exception as e:
            logger.error(f"[ExamGraph] PDF 生成失敗: {e}")
            response.warnings.append(f"PDF 生成失敗: {str(e)}")
    
    # 保存考試到資料庫
    if response.questions:
        try:
            # 從文件獲取 class_id 和 owner_id
            class_id, owner_id = await _get_class_and_owner_from_files(request.file_ids)
            
            # 將題目轉換為 dict 格式
            questions_dict = [q.model_dump() for q in response.questions]
            
            # 保存到資料庫
            save_result = await asyncio.to_thread(
                pg_service.save_exam,
                response.exam_id,
                response.exam_name,
                questions_dict,
                request.file_ids,
                class_id,
                owner_id,
                request.difficulty,
                None,  # duration_minutes（可選）
                response.pdf_path,
                None,  # description（可選）
            )
            
            logger.info(f"[ExamGraph] 考試已保存到資料庫 - ID: {save_result['exam_id']}, 標題: {save_result['title']}")
            
        except Exception as e:
            logger.error(f"[ExamGraph] 保存考試到資料庫失敗: {e}")
            response.warnings.append(f"保存到資料庫失敗: {str(e)}")
    
    return response


async def _get_class_and_owner_from_files(file_ids: List[str]) -> tuple:
    """
    從文件列表獲取 class_id 和 owner_id (teacher_id)
    假設所有文件屬於同一個班級
    
    Returns:
        (class_id, owner_id) 元組
    """
    if not file_ids:
        return None, None
    
    try:
        from app.services.pg_db import _get_conn
        
        def _query():
            with _get_conn() as conn, conn.cursor() as cur:
                # 獲取 class_id 和對應的 teacher_id
                cur.execute("""
                    SELECT DISTINCT d.class_id, c.teacher_id
                    FROM documents d
                    LEFT JOIN classes c ON c.id = d.class_id
                    WHERE d.id = ANY(%s::uuid[]) AND d.class_id IS NOT NULL
                """, (file_ids,))
                rows = cur.fetchall()
                if rows and len(rows) == 1:
                    class_id = str(rows[0]["class_id"]) if rows[0]["class_id"] else None
                    owner_id = str(rows[0]["teacher_id"]) if rows[0]["teacher_id"] else None
                    return class_id, owner_id
                return None, None
        
        return await asyncio.to_thread(_query)
    except Exception as e:
        logger.warning(f"[ExamGraph] 獲取 class_id/owner_id 失敗: {e}")
        return None, None

