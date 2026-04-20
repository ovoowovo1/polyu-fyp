# -*- coding: utf-8 -*-
"""
Pydantic Schemas for Exam Generation System
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# Bloom 認知層級
BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]

# 難度級別
Difficulty = Literal["easy", "medium", "difficult"]

# 題目類型
QuestionType = Literal["multiple_choice", "short_answer", "essay", "calculation"]


class MarkingCriterion(BaseModel):
    """評分標準項目"""
    criterion: str = Field(..., description="評分項目描述")
    marks: int = Field(..., description="該項目配分")
    explanation: str = Field(..., description="給分說明")


class ExamQuestion(BaseModel):
    """考試題目結構"""
    model_config = {"protected_namespaces": ()}  # 允許使用 model_ 前綴
    
    question_id: str = Field(..., description="題目唯一識別碼")
    question_type: QuestionType = Field(default="multiple_choice", description="題目類型")
    bloom_level: BloomLevel = Field(..., description="Bloom 認知層級")
    
    question_text: str = Field(..., description="題目內容")
    
    # 選擇題專用
    choices: Optional[List[str]] = Field(default=None, description="選項列表（選擇題）")
    correct_answer_index: Optional[int] = Field(default=None, ge=0, le=3, description="正確答案索引")
    
    # 非選擇題答案
    model_answer: Optional[str] = Field(default=None, description="標準答案/參考答案")
    
    # 評分標準
    marks: int = Field(default=1, description="題目配分")
    marking_scheme: List[MarkingCriterion] = Field(default_factory=list, description="評分標準")
    rationale: str = Field(..., description="答案解釋")
    
    # 圖表相關
    image_description: Optional[str] = Field(
        default=None, 
        description="若需要圖表，描述圖表內容（將由 Visualizer 生成）"
    )
    image_path: Optional[str] = Field(default=None, description="生成的圖表路徑")
    
    # 來源追蹤
    source_chunk_ids: List[str] = Field(default_factory=list, description="來源 chunk IDs")


class ReviewIssue(BaseModel):
    """審核問題項目"""
    question_id: str = Field(..., description="有問題的題目 ID")
    issue_type: Literal["context_mismatch", "answer_error", "marking_unclear", "image_issue"] = Field(
        ..., description="問題類型"
    )
    description: str = Field(..., description="問題描述")
    suggestion: str = Field(..., description="修改建議")


class ReviewResult(BaseModel):
    """審核結果"""
    is_valid: bool = Field(..., description="是否通過審核")
    overall_score: float = Field(..., ge=0, le=100, description="整體品質分數")
    issues: List[ReviewIssue] = Field(default_factory=list, description="發現的問題列表")
    summary: str = Field(..., description="審核摘要")


class QuestionTypeConfig(BaseModel):
    """題型數量配置"""
    multiple_choice: int = Field(default=0, ge=0, le=50, description="選擇題數量")
    short_answer: int = Field(default=0, ge=0, le=20, description="簡答題數量")
    essay: int = Field(default=0, ge=0, le=10, description="長答題/論述題數量")


class ExamGenerationRequest(BaseModel):
    """考試生成請求"""
    file_ids: List[str] = Field(..., min_length=1, description="文件 ID 列表")
    topic: Optional[str] = Field(default=None, description="考試主題（可選，若不提供則自動推斷）")
    difficulty: Difficulty = Field(default="medium", description="難度級別")
    num_questions: int = Field(default=10, ge=1, le=50, description="題目數量（向後兼容）")
    question_types: Optional[QuestionTypeConfig] = Field(default=None, description="各題型數量配置")
    exam_name: Optional[str] = Field(default=None, description="考試名稱（可選）")
    include_images: bool = Field(default=True, description="是否包含圖表")
    custom_prompt: Optional[str] = Field(default=None, max_length=1000, description="用戶自定義需求（可選）")


class ExamGenerationResponse(BaseModel):
    """考試生成響應"""
    exam_id: str = Field(..., description="考試 ID")
    exam_name: str = Field(..., description="考試名稱")
    questions: List[ExamQuestion] = Field(..., description="生成的題目")
    pdf_path: Optional[str] = Field(default=None, description="PDF 檔案路徑")
    warnings: List[str] = Field(default_factory=list, description="警告訊息")
    review_score: float = Field(..., description="品質評分")


# 用於 Gemini 結構化輸出的簡化 Schema
class _MCQuestion(BaseModel):
    """Gemini 輸出用 - 選擇題"""
    question_type: str = "multiple_choice"
    bloom_level: BloomLevel
    question_text: str
    choices: List[str]
    correct_answer_index: int
    rationale: str
    marks: int = 1
    image_description: Optional[str] = None
    marking_criteria: Optional[List[str]] = None


class _ShortAnswerQuestion(BaseModel):
    """Gemini 輸出用 - 簡答題"""
    model_config = {"protected_namespaces": ()}
    
    question_type: str = "short_answer"
    bloom_level: BloomLevel
    question_text: str
    model_answer: str
    rationale: str
    marks: int = 3
    image_description: Optional[str] = None
    marking_criteria: Optional[List[str]] = None


class _EssayQuestion(BaseModel):
    """Gemini 輸出用 - 長答題/論述題"""
    model_config = {"protected_namespaces": ()}
    
    question_type: str = "essay"
    bloom_level: BloomLevel
    question_text: str
    model_answer: str
    rationale: str
    marks: int = 5
    image_description: Optional[str] = None
    marking_criteria: Optional[List[str]] = None


class _GeneratorOutput(BaseModel):
    """Gemini Generator 輸出結構"""
    exam_name: str
    questions: List[_MCQuestion]


class _MixedGeneratorOutput(BaseModel):
    """Gemini Generator 混合題型輸出結構"""
    exam_name: str
    multiple_choice_questions: Optional[List[_MCQuestion]] = None
    short_answer_questions: Optional[List[_ShortAnswerQuestion]] = None
    essay_questions: Optional[List[_EssayQuestion]] = None

