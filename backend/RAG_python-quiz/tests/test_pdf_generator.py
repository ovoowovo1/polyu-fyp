import unittest
from types import SimpleNamespace
from unittest.mock import patch

from reportlab.platypus import Paragraph, Spacer, Table

from app.agents.schemas import ExamQuestion, MarkingCriterion
from app.utils import pdf_generator as pdf_generator_module


def _paragraph_texts(elements):
    texts = []
    for element in elements:
        if isinstance(element, Paragraph):
            if hasattr(element, "getPlainText"):
                texts.append(element.getPlainText())
            else:
                texts.append(getattr(element, "text", ""))
    return texts


def _first_table(elements):
    return next(element for element in elements if isinstance(element, Table))


def criterion(text, marks=1, explanation=None):
    return MarkingCriterion(criterion=text, marks=marks, explanation=explanation or text)


def exam_question(question_type="multiple_choice", **overrides):
    defaults = {
        "question_id": {"multiple_choice": "q1", "short_answer": "q2", "essay": "q3"}[question_type],
        "question_type": question_type,
        "bloom_level": {"multiple_choice": "analyze", "short_answer": "analyze", "essay": "evaluate"}[question_type],
        "question_text": {"multiple_choice": "MCQ", "short_answer": "Short", "essay": "Essay"}[question_type],
        "marks": {"multiple_choice": 1, "short_answer": 3, "essay": 5}[question_type],
        "rationale": {"multiple_choice": "MCQ explanation", "short_answer": "Short explanation", "essay": "Essay explanation"}[question_type],
    }
    if question_type == "multiple_choice":
        defaults.update(choices=["A", "B", "C", "D"], correct_answer_index=1)
    else:
        defaults["model_answer"] = {"short_answer": "Short answer", "essay": "Essay answer"}[question_type]
    defaults.update(overrides)
    return ExamQuestion(**defaults)


def raw_mcq_question(**overrides):
    defaults = {
        "question_id": "q1",
        "question_type": "multiple_choice",
        "bloom_level": "analyze",
        "question_text": "MCQ",
        "choices": ["A", "B", "C", "D"],
        "correct_answer_index": 1,
        "marks": 1,
        "rationale": "MCQ explanation",
        "model_answer": None,
        "marking_scheme": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PdfGeneratorTests(unittest.TestCase):
    def test_register_chinese_fonts_covers_success_and_fallback(self):
        with patch("app.utils.pdf_generator.os.path.exists", side_effect=lambda path: path.endswith("msyh.ttc")), patch(
            "app.utils.pdf_generator.pdfmetrics.registerFont"
        ) as register_font, patch(
            "app.utils.pdf_generator.TTFont",
            return_value="font",
        ):
            self.assertEqual(pdf_generator_module._register_chinese_fonts(), "ChineseFont")
        register_font.assert_called_once()

        with patch("app.utils.pdf_generator.os.path.exists", return_value=True), patch(
            "app.utils.pdf_generator.pdfmetrics.registerFont",
            side_effect=RuntimeError("bad font"),
        ), patch(
            "app.utils.pdf_generator.TTFont",
            return_value="font",
        ):
            self.assertEqual(pdf_generator_module._register_chinese_fonts(), "Helvetica")

    def test_cover_page_and_answer_table_use_question_marks(self):
        questions = [
            exam_question(),
            exam_question("short_answer", marking_scheme=[criterion("Point 1", 2), criterion("Point 2")]),
            exam_question("essay", marking_scheme=[criterion("Argument", 3), criterion("Support", 2)]),
        ]

        styles = pdf_generator_module._create_styles()
        total_marks = sum(question.marks for question in questions)

        cover_elements = pdf_generator_module._build_cover_page("Generated Exam", len(questions), total_marks, styles)
        cover_table = _first_table(cover_elements)
        self.assertEqual(cover_table._cellvalues[0][1], "3")
        self.assertEqual(cover_table._cellvalues[1][1], "9")

        answer_elements = pdf_generator_module._build_answer_key(questions, styles)
        answer_table = _first_table(answer_elements)
        self.assertEqual(answer_table._cellvalues[1], ["1", "MCQ", "B", "1"])
        self.assertEqual(answer_table._cellvalues[2], ["2", "Short", "See Expl.", "3"])
        self.assertEqual(answer_table._cellvalues[3], ["3", "Essay", "See Expl.", "5"])

    def test_build_questions_section_covers_images_answers_and_rationale(self):
        questions = [
            exam_question(image_path="/static/images/q1.png"),
            exam_question("short_answer"),
            exam_question("essay"),
        ]
        styles = pdf_generator_module._create_styles()

        fake_image = SimpleNamespace(hAlign=None)
        with patch("app.utils.pdf_generator.os.path.exists", side_effect=lambda path: path.endswith("q1.png")), patch(
            "app.utils.pdf_generator.Image",
            return_value=fake_image,
        ):
            elements = pdf_generator_module._build_questions_section(questions, styles, include_answers=True)

        texts = _paragraph_texts(elements)
        self.assertIn("Question 1 (1 marks) [Analyze]", texts)
        self.assertIn("Reference Answer:", texts)
        self.assertIn("Explanation: Essay explanation", texts)
        self.assertEqual(fake_image.hAlign, "CENTER")
        self.assertIn(fake_image, elements)
        self.assertTrue(any(text == "(A) A" for text in texts))

        with patch("app.utils.pdf_generator.os.path.exists", return_value=True), patch(
            "app.utils.pdf_generator.Image",
            side_effect=RuntimeError("bad image"),
        ):
            elements = pdf_generator_module._build_questions_section(questions[:1], styles, include_answers=False)
        self.assertTrue(elements)

    def test_build_questions_section_hits_image_spacers_and_plain_choices(self):
        question = raw_mcq_question(
            bloom_level="remember",
            image_path="/static/images/q1.png",
        )
        styles = pdf_generator_module._create_styles()
        fake_image = SimpleNamespace(hAlign=None)

        with patch("app.utils.pdf_generator.os.path.exists", return_value=True), patch(
            "app.utils.pdf_generator.Image",
            return_value=fake_image,
        ):
            elements = pdf_generator_module._build_questions_section([question], styles, include_answers=False)

        spacer_count = sum(1 for element in elements if isinstance(element, Spacer))
        texts = _paragraph_texts(elements)
        self.assertGreaterEqual(spacer_count, 4)
        self.assertIn(fake_image, elements)
        self.assertIn("(B) B", texts)

    def test_answer_key_hides_mcq_marking_scheme(self):
        questions = [
            exam_question(correct_answer_index=0, marking_scheme=[criterion("Should not render", explanation="Ignore")]),
            exam_question("short_answer", marking_scheme=[criterion("Point 1", 2), criterion("Point 2")]),
        ]

        styles = pdf_generator_module._create_styles()
        answer_elements = pdf_generator_module._build_answer_key(questions, styles)
        texts = _paragraph_texts(answer_elements)

        mcq_start = texts.index("Question 1 [MCQ]")
        short_start = texts.index("Question 2 [Short]")
        mcq_section = texts[mcq_start:short_start]
        short_section = texts[short_start:]

        self.assertIn("Correct Answer: (A) A", mcq_section)
        self.assertNotIn("Marking Scheme:", mcq_section)
        self.assertIn("Marking Scheme:", short_section)

    def test_answer_key_renders_rubric_explanations_without_duplicates(self):
        questions = [
            exam_question(
                "short_answer",
                question_id="q1",
                marking_scheme=[
                    criterion("Definition Accuracy", 2, "Correctly differentiates between principal and subject."),
                    criterion("Conceptual Insight"),
                ],
            ),
        ]

        styles = pdf_generator_module._create_styles()
        answer_elements = pdf_generator_module._build_answer_key(questions, styles)
        texts = _paragraph_texts(answer_elements)

        self.assertIn("• Definition Accuracy (2 marks)", texts)
        self.assertIn("Correctly differentiates between principal and subject.", texts)
        self.assertIn("• Conceptual Insight (1 marks)", texts)
        self.assertEqual(
            [text for text in texts if "Conceptual Insight" in text],
            ["• Conceptual Insight (1 marks)"],
        )

    def test_answer_key_uses_question_mark_for_invalid_mcq_index(self):
        question = raw_mcq_question(correct_answer_index=5)
        styles = pdf_generator_module._create_styles()
        answer_elements = pdf_generator_module._build_answer_key([question], styles)
        answer_table = _first_table(answer_elements)
        self.assertEqual(answer_table._cellvalues[1], ["1", "MCQ", "?", "1"])

    def test_generate_exam_pdf_builds_document_and_returns_relative_path(self):
        import asyncio

        questions = [exam_question()]

        class FakeDoc:
            def __init__(self, *args, **kwargs):
                self.built = None

            def build(self, elements):
                self.built = elements

        fake_doc = FakeDoc()

        async def run(include_answers):
            with patch("app.utils.pdf_generator.SimpleDocTemplate", return_value=fake_doc), patch(
                "app.utils.pdf_generator._create_styles",
                return_value={"SectionTitle": object()},
            ), patch(
                "app.utils.pdf_generator._build_cover_page",
                return_value=["cover"],
            ), patch(
                "app.utils.pdf_generator._build_questions_section",
                return_value=["questions"],
            ), patch(
                "app.utils.pdf_generator._build_answer_key",
                return_value=["answers"],
            ):
                return await pdf_generator_module.generate_exam_pdf(
                    "exam-1",
                    "Exam",
                    questions,
                    include_answers=include_answers,
                )

        path_with_answers = asyncio.run(run(True))
        self.assertEqual(path_with_answers, "/static/pdfs/exam-1.pdf")
        self.assertEqual(fake_doc.built, ["cover", "questions", "answers"])

        fake_doc.built = None
        path_without_answers = asyncio.run(run(False))
        self.assertEqual(path_without_answers, "/static/pdfs/exam-1.pdf")
        self.assertEqual(fake_doc.built, ["cover", "questions"])


if __name__ == "__main__":
    unittest.main()
