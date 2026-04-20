import asyncio
import os
from datetime import datetime
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.agents.schemas import ExamQuestion
from app.logger import get_logger

logger = get_logger(__name__)

PDF_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "pdfs")
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "images")


def _register_chinese_fonts():
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                logger.info("[PDFGen] Registered font: %s", font_path)
                return "ChineseFont"
            except Exception as error:
                logger.warning("[PDFGen] Failed to register font %s: %s", font_path, error)
    logger.warning("[PDFGen] Falling back to Helvetica")
    return "Helvetica"


CHINESE_FONT = _register_chinese_fonts()


def _create_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ExamTitle", fontName=CHINESE_FONT, fontSize=24, leading=30, alignment=1, spaceAfter=20))
    styles.add(ParagraphStyle(name="ExamSubtitle", fontName=CHINESE_FONT, fontSize=14, leading=18, alignment=1, spaceAfter=10, textColor=colors.grey))
    styles.add(ParagraphStyle(name="SectionTitle", fontName=CHINESE_FONT, fontSize=16, leading=20, spaceBefore=20, spaceAfter=10, textColor=colors.HexColor("#2c3e50")))
    styles.add(ParagraphStyle(name="QuestionTitle", fontName=CHINESE_FONT, fontSize=12, leading=16, spaceBefore=15, spaceAfter=5, textColor=colors.HexColor("#34495e")))
    styles.add(ParagraphStyle(name="QuestionText", fontName=CHINESE_FONT, fontSize=11, leading=15, spaceAfter=8))
    styles.add(ParagraphStyle(name="Choice", fontName=CHINESE_FONT, fontSize=10, leading=14, leftIndent=20, spaceAfter=3))
    styles.add(ParagraphStyle(name="Answer", fontName=CHINESE_FONT, fontSize=10, leading=14, textColor=colors.HexColor("#27ae60")))
    styles.add(ParagraphStyle(name="Rationale", fontName=CHINESE_FONT, fontSize=10, leading=14, textColor=colors.HexColor("#7f8c8d"), leftIndent=20))
    styles.add(ParagraphStyle(name="RubricExplanation", fontName=CHINESE_FONT, fontSize=9, leading=13, textColor=colors.HexColor("#7f8c8d"), leftIndent=36, spaceAfter=3))
    styles.add(ParagraphStyle(name="Footer", fontName=CHINESE_FONT, fontSize=8, alignment=1, textColor=colors.grey))
    return styles


def _build_cover_page(exam_name: str, num_questions: int, total_marks: int, styles: dict) -> List:
    elements = [Spacer(1, 5 * cm), Paragraph(exam_name, styles["ExamTitle"]), Paragraph("Examination Paper", styles["ExamSubtitle"]), Spacer(1, 2 * cm)]
    info_table = Table(
        [
            ["Total Questions", f"{num_questions}"],
            ["Total Marks", f"{total_marks}"],
            ["Generated Date", datetime.now().strftime("%Y-%m-%d %H:%M")],
        ],
        colWidths=[5 * cm, 8 * cm],
    )
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), CHINESE_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    instructions = (
        "<b>Exam Instructions:</b><br/>"
        "1. Please read each question carefully.<br/>"
        "2. Multiple choice questions have only one correct answer.<br/>"
        "3. Please write your answers on the answer sheet.<br/>"
        "4. Please submit the paper after the exam."
    )
    elements.extend([info_table, Spacer(1, 3 * cm), Paragraph(instructions, styles["QuestionText"]), PageBreak()])
    return elements


def _build_questions_section(questions: List[ExamQuestion], styles: dict, include_answers: bool = False) -> List:
    elements = [Paragraph("Questions", styles["SectionTitle"]), Spacer(1, 0.5 * cm)]
    bloom_labels = {
        "remember": "Remember",
        "understand": "Understand",
        "apply": "Apply",
        "analyze": "Analyze",
        "evaluate": "Evaluate",
        "create": "Create",
    }
    choice_labels = ["A", "B", "C", "D"]

    for index, question in enumerate(questions, 1):
        bloom_label = bloom_labels.get(question.bloom_level, question.bloom_level)
        elements.append(Paragraph(f"Question {index} ({question.marks} marks) [{bloom_label}]", styles["QuestionTitle"]))
        elements.append(Paragraph(question.question_text, styles["QuestionText"]))

        if question.image_path:
            image_path = os.path.join(IMAGES_DIR, question.image_path.replace("/static/images/", "")) if question.image_path.startswith("/static/images/") else question.image_path
            if os.path.exists(image_path):
                try:
                    image = Image(image_path, width=12 * cm, height=8 * cm)
                    image.hAlign = "CENTER"
                    elements.extend([Spacer(1, 0.3 * cm), image, Spacer(1, 0.3 * cm)])
                except Exception as error:
                    logger.warning("[PDFGen] Failed to render image %s: %s", image_path, error)

        if question.question_type == "multiple_choice" and question.choices:
            for choice_index, choice in enumerate(question.choices[: len(choice_labels)]):
                prefix = f"({choice_labels[choice_index]}) {choice}"
                if include_answers and question.correct_answer_index is not None and choice_index == question.correct_answer_index:
                    elements.append(Paragraph(f"<b>{prefix}</b>", styles["Answer"]))
                else:
                    elements.append(Paragraph(prefix, styles["Choice"]))
        elif question.question_type in ["short_answer", "essay"]:
            answer_lines = 5 if question.question_type == "short_answer" else 10
            elements.append(Paragraph(f"<i>(Please answer below, approx. {answer_lines} lines)</i>", styles["Choice"]))
            elements.append(Spacer(1, answer_lines * 0.5 * cm))
            if include_answers and question.model_answer:
                elements.append(Paragraph("<b>Reference Answer:</b>", styles["QuestionText"]))
                elements.append(Paragraph(question.model_answer, styles["Answer"]))

        if include_answers and question.rationale:
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph(f"<i>Explanation: {question.rationale}</i>", styles["Rationale"]))
        elements.append(Spacer(1, 0.5 * cm))

    return elements


def _build_answer_key(questions: List[ExamQuestion], styles: dict) -> List:
    elements = [PageBreak(), Paragraph("Answers and Explanations", styles["SectionTitle"]), Spacer(1, 0.5 * cm)]
    choice_labels = ["A", "B", "C", "D"]
    type_labels = {"multiple_choice": "MCQ", "short_answer": "Short", "essay": "Essay"}
    answer_data = [["No.", "Type", "Answer", "Marks"]]

    for index, question in enumerate(questions, 1):
        if question.question_type == "multiple_choice" and question.correct_answer_index is not None and question.choices:
            answer = choice_labels[question.correct_answer_index] if 0 <= question.correct_answer_index < len(choice_labels) else "?"
        else:
            answer = "See Expl."
        answer_data.append([str(index), type_labels.get(question.question_type, "Other"), answer, str(question.marks)])

    answer_table = Table(answer_data, colWidths=[1.5 * cm, 1.5 * cm, 2 * cm, 1.5 * cm])
    answer_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), CHINESE_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecf0f1")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.extend([answer_table, Spacer(1, 1 * cm), Paragraph("Detailed Explanations", styles["SectionTitle"])])

    for index, question in enumerate(questions, 1):
        type_label = type_labels.get(question.question_type, "Other")
        elements.append(Paragraph(f"<b>Question {index} [{type_label}]</b>", styles["QuestionTitle"]))
        if question.question_type == "multiple_choice":
            if question.correct_answer_index is not None and question.choices and 0 <= question.correct_answer_index < len(question.choices):
                answer_text = f"Correct Answer: ({choice_labels[question.correct_answer_index]}) {question.choices[question.correct_answer_index]}"
                elements.append(Paragraph(answer_text, styles["Answer"]))
        else:
            if question.model_answer:
                elements.append(Paragraph("<b>Reference Answer:</b>", styles["QuestionText"]))
                elements.append(Paragraph(question.model_answer, styles["Answer"]))

        if question.rationale:
            elements.append(Paragraph(f"Explanation: {question.rationale}", styles["Rationale"]))

        if question.question_type != "multiple_choice" and question.marking_scheme:
            elements.append(Paragraph("<b>Marking Scheme:</b>", styles["QuestionText"]))
            for criterion in question.marking_scheme:
                elements.append(Paragraph(f"• {criterion.criterion} ({criterion.marks} marks)", styles["Rationale"]))
                explanation_text = (criterion.explanation or "").strip()
                criterion_text = (criterion.criterion or "").strip()
                if explanation_text and explanation_text != criterion_text:
                    elements.append(Paragraph(explanation_text, styles["RubricExplanation"]))

        elements.append(Spacer(1, 0.3 * cm))

    return elements


async def generate_exam_pdf(exam_id: str, exam_name: str, questions: List[ExamQuestion], include_answers: bool = True) -> str:
    logger.info("[PDFGen] Generating PDF exam=%s questions=%s", exam_name, len(questions))
    pdf_filename = f"{exam_id}.pdf"
    pdf_path = os.path.join(PDF_OUTPUT_DIR, pdf_filename)
    total_marks = sum(question.marks for question in questions)
    styles = _create_styles()
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    elements = []
    elements.extend(_build_cover_page(exam_name, len(questions), total_marks, styles))
    elements.extend(_build_questions_section(questions, styles, include_answers=False))
    if include_answers:
        elements.extend(_build_answer_key(questions, styles))

    def _build_pdf():
        doc.build(elements)

    await asyncio.to_thread(_build_pdf)
    logger.info("[PDFGen] PDF generated: %s", pdf_path)
    return f"/static/pdfs/{pdf_filename}"
