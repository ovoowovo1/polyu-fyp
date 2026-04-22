# -*- coding: utf-8 -*-
"""
Shared State Definition for LangGraph Exam Generation
"""

from typing import TypedDict, List, Dict, Any, Optional
from app.agents.schemas import ExamQuestion, ReviewResult


class ExamGenerationState(TypedDict):
    """
    LangGraph 狀態定義 - 在各節點之間傳遞的共享狀態
    """
    # 輸入參數
    file_ids: List[str]
    topic: str
    difficulty: str  # easy, medium, difficult
    num_questions: int
    question_types: Optional[Dict[str, int]]  # {"multiple_choice": 5, "short_answer": 3, "essay": 2}
    custom_prompt: str  # 用戶自定義需求
    
    # RAG 檢索結果
    context: str
    context_chunks: List[Dict[str, Any]]
    retrieval_evidence: Dict[str, Any]
    
    # 生成的題目
    questions: List[ExamQuestion]
    
    # 圖表相關
    images: Dict[str, str]  # question_id -> image_path
    
    # 審核相關
    review_result: Optional[ReviewResult]
    feedback: str
    retry_count: int
    max_retries: int

    # 迭代檢索相關
    search_iterations: int  # 當前檢索重試次數
    max_search_iterations: int # 最大檢索重試次數
    research_goal: Optional[str]  # 審核員提出的具體補強搜尋目標
    
    # 考試元資料
    exam_name: str
    exam_id: str
    
    # 最終輸出
    pdf_path: Optional[str]
    warnings: List[str]
    is_complete: bool
