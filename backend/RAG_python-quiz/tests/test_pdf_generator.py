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
            ExamQuestion(
                question_id="q1",
                question_type="multiple_choice",
                bloom_level="analyze",
                question_text="MCQ",
                choices=["A", "B", "C", "D"],
                correct_answer_index=1,
                marks=1,
                rationale="MCQ explanation",
            ),
            ExamQuestion(
                question_id="q2",
                question_type="short_answer",
                bloom_level="analyze",
                question_text="Short",
                model_answer="Short answer",
                marks=3,
                marking_scheme=[
                    MarkingCriterion(criterion="Point 1", marks=2, explanation="Point 1"),
                    MarkingCriterion(criterion="Point 2", marks=1, explanation="Point 2"),
                ],
                rationale="Short explanation",
            ),
            ExamQuestion(
                question_id="q3",
                question_type="essay",
                bloom_level="evaluate",
                question_text="Essay",
                model_answer="Essay answer",
                marks=5,
                marking_scheme=[
                    MarkingCriterion(criterion="Argument", marks=3, explanation="Argument"),
                    MarkingCriterion(criterion="Support", marks=2, explanation="Support"),
                ],
                rationale="Essay explanation",
            ),
        ]

        styles = pdf_generator_module._create_styles()
        total_marks = sum(question.marks for question in questions)

        cover_elements = pdf_generator_module._build_cover_page("Generated Exam", len(questions), total_marks, styles)
        cover_table = next(element for element in cover_elements if isinstance(element, Table))
        self.assertEqual(cover_table._cellvalues[0][1], "3")
        self.assertEqual(cover_table._cellvalues[1][1], "9")

        answer_elements = pdf_generator_module._build_answer_key(questions, styles)
        answer_table = next(element for element in answer_elements if isinstance(element, Table))
        self.assertEqual(answer_table._cellvalues[1], ["1", "MCQ", "B", "1"])
        self.assertEqual(answer_table._cellvalues[2], ["2", "Short", "See Expl.", "3"])
        self.assertEqual(answer_table._cellvalues[3], ["3", "Essay", "See Expl.", "5"])

    def test_build_questions_section_covers_images_answers_and_rationale(self):
        questions = [
            ExamQuestion(
                question_id="q1",
                question_type="multiple_choice",
                bloom_level="analyze",
                question_text="MCQ",
                choices=["A", "B", "C", "D"],
                correct_answer_index=1,
                marks=1,
                rationale="MCQ explanation",
                image_path="/static/images/q1.png",
            ),
            ExamQuestion(
                question_id="q2",
                question_type="short_answer",
                bloom_level="analyze",
                question_text="Short",
                model_answer="Short answer",
                marks=3,
                rationale="Short explanation",
            ),
            ExamQuestion(
                question_id="q3",
                question_type="essay",
                bloom_level="evaluate",
                question_text="Essay",
                model_answer="Essay answer",
                marks=5,
                rationale="Essay explanation",
            ),
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
        question = SimpleNamespace(
            question_id="q1",
            question_type="multiple_choice",
            bloom_level="remember",
            question_text="MCQ",
            choices=["A", "B", "C", "D"],
            correct_answer_index=1,
            marks=1,
            rationale="MCQ explanation",
            image_path="/static/images/q1.png",
            model_answer=None,
            marking_scheme=[],
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
            ExamQuestion(
                question_id="q1",
                question_type="multiple_choice",
                bloom_level="analyze",
                question_text="MCQ",
                choices=["A", "B", "C", "D"],
                correct_answer_index=0,
                marks=1,
                marking_scheme=[
                    MarkingCriterion(criterion="Should not render", marks=1, explanation="Ignore"),
                ],
                rationale="MCQ explanation",
            ),
            ExamQuestion(
                question_id="q2",
                question_type="short_answer",
                bloom_level="analyze",
                question_text="Short",
                model_answer="Short answer",
                marks=3,
                marking_scheme=[
                    MarkingCriterion(criterion="Point 1", marks=2, explanation="Point 1"),
                    MarkingCriterion(criterion="Point 2", marks=1, explanation="Point 2"),
                ],
                rationale="Short explanation",
            ),
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
            ExamQuestion(
                question_id="q1",
                question_type="short_answer",
                bloom_level="analyze",
                question_text="Short",
                model_answer="Short answer",
                marks=3,
                marking_scheme=[
                    MarkingCriterion(
                        criterion="Definition Accuracy",
                        marks=2,
                        explanation="Correctly differentiates between principal and subject.",
                    ),
                    MarkingCriterion(
                        criterion="Conceptual Insight",
                        marks=1,
                        explanation="Conceptual Insight",
                    ),
                ],
                rationale="Short explanation",
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
        question = SimpleNamespace(
            question_id="q1",
            question_type="multiple_choice",
            bloom_level="analyze",
            question_text="MCQ",
            choices=["A", "B", "C", "D"],
            correct_answer_index=5,
            marks=1,
            rationale="MCQ explanation",
            model_answer=None,
            marking_scheme=[],
        )
        styles = pdf_generator_module._create_styles()
        answer_elements = pdf_generator_module._build_answer_key([question], styles)
        answer_table = next(element for element in answer_elements if isinstance(element, Table))
        self.assertEqual(answer_table._cellvalues[1], ["1", "MCQ", "?", "1"])

    def test_generate_exam_pdf_builds_document_and_returns_relative_path(self):
        import asyncio

        questions = [
            ExamQuestion(
                question_id="q1",
                question_type="multiple_choice",
                bloom_level="analyze",
                question_text="MCQ",
                choices=["A", "B", "C", "D"],
                correct_answer_index=1,
                marks=1,
                rationale="MCQ explanation",
            )
        ]

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
