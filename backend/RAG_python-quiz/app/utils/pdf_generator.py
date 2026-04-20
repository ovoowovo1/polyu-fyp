# -*- coding: utf-8 -*-
"""
PDF Generator - 考試 PDF 生成器
使用 ReportLab 生成包含封面、題目、答案和評分標準的 PDF
"""

import os
import asyncio
from typing import List, Optional
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
    ListFlowable,
    ListItem,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.agents.schemas import ExamQuestion
from app.logger import get_logger

logger = get_logger(__name__)

# PDF 輸出目錄
PDF_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "static",
    "pdfs"
)
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

# 圖片目錄
IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "static",
    "images"
)

# 嘗試註冊中文字體
def _register_chinese_fonts():
    """嘗試註冊中文字體"""
    # Windows 字體路徑
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",  # 微軟雅黑
        "C:/Windows/Fonts/simsun.ttc",  # 宋體
        "C:/Windows/Fonts/simhei.ttf",  # 黑體
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux WQY
        "/System/Library/Fonts/PingFang.ttc",  # macOS
    ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                logger.info(f"[PDFGen] 已註冊中文字體: {font_path}")
                return "ChineseFont"
            except Exception as e:
                logger.warning(f"[PDFGen] 註冊字體失敗 {font_path}: {e}")
    
    logger.warning("[PDFGen] 未找到中文字體，將使用預設字體")
    return "Helvetica"

# 初始化字體
CHINESE_FONT = _register_chinese_fonts()


def _create_styles():
    """創建 PDF 樣式"""
    styles = getSampleStyleSheet()
    
    # 標題樣式
    styles.add(ParagraphStyle(
        name='ExamTitle',
        fontName=CHINESE_FONT,
        fontSize=24,
        leading=30,
        alignment=1,  # 居中
        spaceAfter=20,
    ))
    
    # 副標題
    styles.add(ParagraphStyle(
        name='ExamSubtitle',
        fontName=CHINESE_FONT,
        fontSize=14,
        leading=18,
        alignment=1,
        spaceAfter=10,
        textColor=colors.grey,
    ))
    
    # 章節標題
    styles.add(ParagraphStyle(
        name='SectionTitle',
        fontName=CHINESE_FONT,
        fontSize=16,
        leading=20,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor('#2c3e50'),
    ))
    
    # 題目標題
    styles.add(ParagraphStyle(
        name='QuestionTitle',
        fontName=CHINESE_FONT,
        fontSize=12,
        leading=16,
        spaceBefore=15,
        spaceAfter=5,
        textColor=colors.HexColor('#34495e'),
    ))
    
    # 題目內容
    styles.add(ParagraphStyle(
        name='QuestionText',
        fontName=CHINESE_FONT,
        fontSize=11,
        leading=15,
        spaceAfter=8,
    ))
    
    # 選項
    styles.add(ParagraphStyle(
        name='Choice',
        fontName=CHINESE_FONT,
        fontSize=10,
        leading=14,
        leftIndent=20,
        spaceAfter=3,
    ))
    
    # 答案
    styles.add(ParagraphStyle(
        name='Answer',
        fontName=CHINESE_FONT,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#27ae60'),
    ))
    
    # 解釋
    styles.add(ParagraphStyle(
        name='Rationale',
        fontName=CHINESE_FONT,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#7f8c8d'),
        leftIndent=20,
    ))

    styles.add(ParagraphStyle(
        name='RubricExplanation',
        fontName=CHINESE_FONT,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#7f8c8d'),
        leftIndent=36,
        spaceAfter=3,
    ))
    
    # 頁尾
    styles.add(ParagraphStyle(
        name='Footer',
        fontName=CHINESE_FONT,
        fontSize=8,
        alignment=1,
        textColor=colors.grey,
    ))
    
    return styles


def _build_cover_page(
    exam_name: str,
    num_questions: int,
    total_marks: int,
    styles: dict
) -> List:
    """建立封面頁"""
    elements = []
    
    # 間距
    elements.append(Spacer(1, 5*cm))
    
    # 考試標題
    elements.append(Paragraph(exam_name, styles['ExamTitle']))
    
    # 副標題
    elements.append(Paragraph("Examination Paper", styles['ExamSubtitle']))
    
    elements.append(Spacer(1, 2*cm))
    
    # 考試信息表格
    info_data = [
        ["Total Questions", f"{num_questions}"],
        ["Total Marks", f"{total_marks}"],
        ["Generated Date", datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    
    info_table = Table(info_data, colWidths=[5*cm, 8*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(info_table)
    
    elements.append(Spacer(1, 3*cm))
    
    # 考試說明
    instructions = """
    <b>Exam Instructions:</b><br/>
    1. Please read each question carefully.<br/>
    2. Multiple choice questions have only one correct answer.<br/>
    3. Please write your answers on the answer sheet.<br/>
    4. Please submit the paper after the exam.
    """
    elements.append(Paragraph(instructions, styles['QuestionText']))
    
    elements.append(PageBreak())
    
    return elements


def _build_questions_section(
    questions: List[ExamQuestion],
    styles: dict,
    include_answers: bool = False
) -> List:
    """建立題目區段"""
    elements = []
    
    # 章節標題
    elements.append(Paragraph("Questions", styles['SectionTitle']))
    elements.append(Spacer(1, 0.5*cm))
    
    for i, q in enumerate(questions, 1):
        # 題目標題（含分數和 Bloom 層級）
        bloom_label = {
            "remember": "Remember",
            "understand": "Understand",
            "apply": "Apply",
            "analyze": "Analyze",
            "evaluate": "Evaluate",
            "create": "Create",
        }.get(q.bloom_level, q.bloom_level)
        
        title = f"Question {i} ({q.marks} marks) [{bloom_label}]"
        elements.append(Paragraph(title, styles['QuestionTitle']))
        
        # 題目內容
        elements.append(Paragraph(q.question_text, styles['QuestionText']))
        
        # 如果有圖片
        if q.image_path:
            # 從相對路徑轉換為絕對路徑
            if q.image_path.startswith("/static/images/"):
                image_filename = q.image_path.replace("/static/images/", "")
                image_full_path = os.path.join(IMAGES_DIR, image_filename)
            else:
                image_full_path = q.image_path
            
            if os.path.exists(image_full_path):
                try:
                    img = Image(image_full_path, width=12*cm, height=8*cm)
                    img.hAlign = 'CENTER'
                    elements.append(Spacer(1, 0.3*cm))
                    elements.append(img)
                    elements.append(Spacer(1, 0.3*cm))
                except Exception as e:
                    logger.warning(f"[PDFGen] 無法載入圖片 {image_full_path}: {e}")
        
        # 根據題型顯示不同內容
        if q.question_type == "multiple_choice" and q.choices:
            # 選擇題：顯示選項
            choice_labels = ['A', 'B', 'C', 'D']
            for j, choice in enumerate(q.choices):
                if j >= len(choice_labels):
                    break
                prefix = f"({choice_labels[j]}) "
                if include_answers and q.correct_answer_index is not None and j == q.correct_answer_index:
                    # 標記正確答案
                    choice_text = f"<b>{prefix}{choice} ✓</b>"
                    elements.append(Paragraph(choice_text, styles['Answer']))
                else:
                    elements.append(Paragraph(f"{prefix}{choice}", styles['Choice']))
        elif q.question_type in ["short_answer", "essay"]:
            # 簡答題/長答題：顯示作答區域
            answer_lines = 5 if q.question_type == "short_answer" else 10
            elements.append(Paragraph(f"<i>(Please answer below, approx. {answer_lines} lines)</i>", styles['Choice']))
            elements.append(Spacer(1, answer_lines * 0.5 * cm))
            
            # 如果包含答案，顯示參考答案
            if include_answers and q.model_answer:
                elements.append(Paragraph(f"<b>Reference Answer:</b>", styles['QuestionText']))
                elements.append(Paragraph(q.model_answer, styles['Answer']))
        
        # 如果包含答案，顯示解釋
        if include_answers and q.rationale:
            elements.append(Spacer(1, 0.2*cm))
            elements.append(Paragraph(f"<i>Explanation: {q.rationale}</i>", styles['Rationale']))
        
        elements.append(Spacer(1, 0.5*cm))
    
    return elements


def _build_answer_key(questions: List[ExamQuestion], styles: dict) -> List:
    """建立答案頁"""
    elements = []
    
    elements.append(PageBreak())
    elements.append(Paragraph("Answers and Explanations", styles['SectionTitle']))
    elements.append(Spacer(1, 0.5*cm))
    
    # 快速答案對照表
    answer_data = [["No.", "Type", "Answer", "Marks"]]
    choice_labels = ['A', 'B', 'C', 'D']
    
    type_labels = {
        "multiple_choice": "MCQ",
        "short_answer": "Short",
        "essay": "Essay"
    }
    
    for i, q in enumerate(questions, 1):
        type_label = type_labels.get(q.question_type, "Other")
        if q.question_type == "multiple_choice" and q.correct_answer_index is not None and q.choices:
            if 0 <= q.correct_answer_index < len(choice_labels):
                answer = choice_labels[q.correct_answer_index]
            else:
                answer = "?"
        else:
            answer = "See Expl."
        answer_data.append([str(i), type_label, answer, str(q.marks)])
    
    # 顯示答案表格
    answer_table = Table(answer_data, colWidths=[1.5*cm, 1.5*cm, 2*cm, 1.5*cm])
    
    answer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(answer_table)
    
    elements.append(Spacer(1, 1*cm))
    
    # 詳細解析
    elements.append(Paragraph("Detailed Explanations", styles['SectionTitle']))
    
    for i, q in enumerate(questions, 1):
        type_label = type_labels.get(q.question_type, "Other")
        elements.append(Paragraph(f"<b>Question {i} [{type_label}]</b>", styles['QuestionTitle']))
        
        # 根據題型顯示答案
        if q.question_type == "multiple_choice":
            if q.correct_answer_index is not None and q.choices and 0 <= q.correct_answer_index < len(q.choices):
                answer = f"Correct Answer: ({choice_labels[q.correct_answer_index]}) {q.choices[q.correct_answer_index]}"
                elements.append(Paragraph(answer, styles['Answer']))
        else:
            # 簡答題/長答題顯示參考答案
            if q.model_answer:
                elements.append(Paragraph("<b>Reference Answer:</b>", styles['QuestionText']))
                elements.append(Paragraph(q.model_answer, styles['Answer']))
        
        if q.rationale:
            elements.append(Paragraph(f"Explanation: {q.rationale}", styles['Rationale']))
        
        # 評分標準
        if q.question_type != "multiple_choice" and q.marking_scheme:
            elements.append(Paragraph("<b>Marking Scheme:</b>", styles['QuestionText']))
            for criterion in q.marking_scheme:
                elements.append(Paragraph(
                    f"• {criterion.criterion} ({criterion.marks} marks)",
                    styles['Rationale']
                ))
                explanation_text = (criterion.explanation or "").strip()
                criterion_text = (criterion.criterion or "").strip()
                if explanation_text and explanation_text != criterion_text:
                    elements.append(Paragraph(
                        explanation_text,
                        styles['RubricExplanation']
                    ))
        
        elements.append(Spacer(1, 0.3*cm))
    
    return elements


async def generate_exam_pdf(
    exam_id: str,
    exam_name: str,
    questions: List[ExamQuestion],
    include_answers: bool = True,
) -> str:
    """
    生成考試 PDF
    
    Args:
        exam_id: 考試 ID
        exam_name: 考試名稱
        questions: 題目列表
        include_answers: 是否包含答案頁
    
    Returns:
        PDF 文件的相對路徑
    """
    logger.info(f"[PDFGen] 開始生成 PDF - 考試: {exam_name}, 題數: {len(questions)}")
    
    # 輸出文件路徑
    pdf_filename = f"{exam_id}.pdf"
    pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)
    
    # 計算總分
    total_marks = sum(q.marks for q in questions)
    
    # 創建樣式
    styles = _create_styles()
    
    # 創建 PDF 文檔
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )
    
    # 組裝內容
    elements = []
    
    # 封面
    elements.extend(_build_cover_page(exam_name, len(questions), total_marks, styles))
    
    # 題目區段
    elements.extend(_build_questions_section(questions, styles, include_answers=False))
    
    # 答案頁
    if include_answers:
        elements.extend(_build_answer_key(questions, styles))
    
    # 生成 PDF（在線程池中執行以避免阻塞）
    def _build_pdf():
        doc.build(elements)
    
    await asyncio.to_thread(_build_pdf)
    
    logger.info(f"[PDFGen] PDF 生成完成: {pdf_path}")
    
    # 返回相對路徑
    return f"/static/pdfs/{pdf_filename}"

