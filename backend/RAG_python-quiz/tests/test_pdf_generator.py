import unittest

from reportlab.platypus import Paragraph, Table

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


if __name__ == "__main__":
    unittest.main()
