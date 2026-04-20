import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents import graph
from app.agents.schemas import ExamGenerationRequest, ExamQuestion, ReviewResult


def make_request(**overrides):
    payload = {
        "file_ids": ["file-1"],
        "topic": "Databases",
        "difficulty": "medium",
        "num_questions": 2,
        "question_types": None,
        "exam_name": "Exam",
        "include_images": True,
        "custom_prompt": None,
    }
    payload.update(overrides)
    return ExamGenerationRequest(**payload)


def make_question():
    return ExamQuestion(
        question_id="q-1",
        question_type="multiple_choice",
        bloom_level="remember",
        question_text="What is SQL?",
        choices=["A", "B", "C", "D"],
        correct_answer_index=1,
        marks=1,
        marking_scheme=[],
        rationale="Basic recall",
        source_chunk_ids=[],
    )


class GraphTests(unittest.IsolatedAsyncioTestCase):
    def test_should_retry_routes_to_expected_node(self):
        self.assertEqual(graph.should_retry({"is_complete": True}), "pdf")
        self.assertEqual(graph.should_retry({"is_complete": False, "research_goal": "transactions"}), "retriever")
        self.assertEqual(graph.should_retry({"is_complete": False}), "generator")

    def test_create_exam_graph_compiles(self):
        compiled = graph.create_exam_graph()
        self.assertTrue(hasattr(compiled, "ainvoke"))

    async def test_run_exam_generation_returns_response(self):
        final_state = {
            "exam_id": "exam-1",
            "exam_name": "Database Exam",
            "questions": [make_question()],
            "pdf_path": None,
            "warnings": [],
            "review_result": ReviewResult(is_valid=True, overall_score=92, issues=[], summary="ok"),
        }
        fake_graph = SimpleNamespace(ainvoke=AsyncMock(return_value=final_state))
        with patch("app.agents.graph.create_exam_graph", return_value=fake_graph):
            response = await graph.run_exam_generation(make_request())

        self.assertEqual(response.exam_id, "exam-1")
        self.assertEqual(response.review_score, 92)

    async def test_run_exam_generation_builds_question_type_distribution(self):
        final_state = {
            "exam_id": "exam-1",
            "exam_name": "Database Exam",
            "questions": [],
            "pdf_path": None,
            "warnings": [],
            "review_result": None,
        }
        fake_graph = SimpleNamespace(ainvoke=AsyncMock(return_value=final_state))
        request = make_request(question_types={"multiple_choice": 1, "short_answer": 1, "essay": 0})
        with patch("app.agents.graph.create_exam_graph", return_value=fake_graph):
            await graph.run_exam_generation(request)

        initial_state = fake_graph.ainvoke.call_args.args[0]
        self.assertEqual(initial_state["question_types"]["multiple_choice"], 1)

    async def test_run_exam_generation_with_pdf_saves_pdf_and_exam(self):
        response = SimpleNamespace(
            exam_id="exam-1",
            exam_name="Database Exam",
            questions=[make_question()],
            pdf_path=None,
            warnings=[],
            review_score=90,
        )
        with patch("app.agents.graph.run_exam_generation", AsyncMock(return_value=response)), patch(
            "app.utils.pdf_generator.generate_exam_pdf",
            AsyncMock(return_value="/tmp/exam-1.pdf"),
        ), patch(
            "app.agents.graph._get_class_and_owner_from_files",
            AsyncMock(return_value=("class-1", "teacher-1")),
        ), patch(
            "app.agents.graph.pg_service.save_exam",
            return_value={"exam_id": "exam-1", "title": "Database Exam"},
        ):
            result = await graph.run_exam_generation_with_pdf(make_request())

        self.assertEqual(result.pdf_path, "/tmp/exam-1.pdf")
        self.assertEqual(result.warnings, [])

    async def test_run_exam_generation_with_pdf_collects_warnings(self):
        response = SimpleNamespace(
            exam_id="exam-1",
            exam_name="Database Exam",
            questions=[make_question()],
            pdf_path=None,
            warnings=[],
            review_score=90,
        )
        with patch("app.agents.graph.run_exam_generation", AsyncMock(return_value=response)), patch(
            "app.utils.pdf_generator.generate_exam_pdf",
            AsyncMock(side_effect=RuntimeError("pdf failed")),
        ), patch(
            "app.agents.graph._get_class_and_owner_from_files",
            AsyncMock(return_value=("class-1", "teacher-1")),
        ), patch(
            "app.agents.graph.pg_service.save_exam",
            side_effect=RuntimeError("save failed"),
        ):
            result = await graph.run_exam_generation_with_pdf(make_request())

        self.assertEqual(len(result.warnings), 2)

    async def test_get_class_and_owner_from_files_handles_no_rows_and_failures(self):
        self.assertEqual(await graph._get_class_and_owner_from_files([]), (None, None))

        class Cursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchall(self):
                return [{"class_id": "class-1", "teacher_id": "teacher-1"}]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class Conn:
            def cursor(self, *args, **kwargs):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        conn = Conn()
        with patch("app.services.pg_db._get_conn", return_value=conn):
            class_id, owner_id = await graph._get_class_and_owner_from_files(["file-1"])
        self.assertEqual((class_id, owner_id), ("class-1", "teacher-1"))

        class MultiRowCursor(Cursor):
            def fetchall(self):
                return [
                    {"class_id": "class-1", "teacher_id": "teacher-1"},
                    {"class_id": "class-2", "teacher_id": "teacher-2"},
                ]

        class MultiConn(Conn):
            def cursor(self, *args, **kwargs):
                return MultiRowCursor()

        with patch("app.services.pg_db._get_conn", return_value=MultiConn()):
            self.assertEqual(await graph._get_class_and_owner_from_files(["file-1"]), (None, None))

        with patch("app.services.pg_db._get_conn", side_effect=RuntimeError("db down")):
            self.assertEqual(await graph._get_class_and_owner_from_files(["file-1"]), (None, None))
