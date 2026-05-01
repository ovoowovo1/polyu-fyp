import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import quiz
from app.services.exceptions import NotFoundError
from app.utils.aqg import MultipleChoice
from tests.support import FakeConnection, FakeCursor, build_app, with_auth


def make_question():
    return MultipleChoice(
        bloom_level="remember",
        question="What is SQL?",
        choices=["A", "B", "C", "D"],
        answer_index=1,
        rationale="Basic recall",
    )


class QuizApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(quiz.router, prefix="/quiz")
        with_auth(app, quiz.get_current_user, {"user_id": "teacher-1", "email": "teacher@example.com"})
        self.client = TestClient(app)

    def test_generate_quiz_happy_path_without_summary(self):
        cursor = FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])
        conn = FakeConnection(cursor)

        async def run():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=conn,
            ), patch(
                "app.routers.quiz.get_settings",
                return_value=SimpleNamespace(llm_model="test-model"),
            ), patch(
                "app.routers.quiz.with_llm_retry_async",
                return_value={"quiz_name": "Quiz", "questions": [make_question()]},
            ), patch(
                "app.routers.quiz.pg_service.save_quiz",
                return_value={"quiz_id": "quiz-1", "name": "Quiz"},
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        response = asyncio.run(run())
        self.assertEqual(response.questions[0].question, "What is SQL?")
        self.assertFalse(response.was_summarized)

    def test_generate_quiz_uses_summary_path_for_long_source(self):
        cursor = FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])
        conn = FakeConnection(cursor)
        long_text = "x" * 13000

        async def run():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value=long_text), patch(
                "app.services.pg_db._get_conn",
                return_value=conn,
            ), patch(
                "app.routers.quiz.get_settings",
                return_value=SimpleNamespace(llm_model="test-model"),
            ), patch(
                "app.routers.quiz.with_llm_retry_async",
                side_effect=["summary", {"quiz_name": "Quiz", "questions": [make_question()]}],
            ), patch(
                "app.routers.quiz.pg_service.save_quiz",
                return_value={"quiz_id": "quiz-1", "name": "Quiz"},
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=None,
                    difficulty="easy",
                    num_questions=1,
                )

        response = asyncio.run(run())
        self.assertTrue(response.was_summarized)
        self.assertEqual(response.source_text_length, len("summary"))

    def test_generate_quiz_validation_and_error_paths(self):
        async def run_empty_files():
            return await quiz.generate_quiz(file_ids=[], bloom_levels=None, difficulty=None, num_questions=1)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run_empty_files())
        self.assertEqual(ctx.exception.status_code, 400)

        cursor = FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])
        conn = FakeConnection(cursor)

        async def run_missing_text():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value=""), patch(
                "app.services.pg_db._get_conn",
                return_value=conn,
            ):
                return await quiz.generate_quiz(file_ids=["file-1"], bloom_levels=None, difficulty=None, num_questions=1)

        with self.assertRaises(HTTPException) as missing_text:
            asyncio.run(run_missing_text())
        self.assertEqual(missing_text.exception.status_code, 400)

        async def run_bad_count():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=conn,
            ):
                return await quiz.generate_quiz(file_ids=["file-1"], bloom_levels=None, difficulty=None, num_questions=100)

        with self.assertRaises(HTTPException) as bad_count:
            asyncio.run(run_bad_count())
        self.assertEqual(bad_count.exception.status_code, 400)

        async def run_difficulty_only():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="   "), patch(
                "app.services.pg_db._get_conn",
                return_value=conn,
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=None,
                    difficulty="easy",
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as blank_text:
            asyncio.run(run_difficulty_only())
        self.assertEqual(blank_text.exception.status_code, 400)

        async def run_bad_class_lookup():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                side_effect=RuntimeError("db down"),
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as bad_class_lookup:
            asyncio.run(run_bad_class_lookup())
        self.assertEqual(bad_class_lookup.exception.status_code, 400)

    def test_generate_quiz_source_and_model_edge_paths(self):
        async def run_missing_source():
            with patch("app.routers.quiz.pg_service.get_files_text_content", side_effect=RuntimeError("missing")):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as missing_source:
            asyncio.run(run_missing_source())
        self.assertEqual(missing_source.exception.status_code, 404)

        async def run_invalid_class():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=FakeConnection(FakeCursor(fetchall_results=[[]])),
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as invalid_class:
            asyncio.run(run_invalid_class())
        self.assertEqual(invalid_class.exception.status_code, 400)

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        async def run_empty_provider():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=FakeConnection(FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])),
            ), patch(
                "app.routers.quiz.get_settings",
                return_value=SimpleNamespace(llm_model="test-model"),
            ), patch(
                "app.routers.quiz.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.routers.quiz.extract_chat_completion_text",
                return_value="",
            ), patch(
                "app.routers.quiz.with_llm_retry_async",
                side_effect=fake_retry,
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as empty_provider:
            asyncio.run(run_empty_provider())
        self.assertEqual(empty_provider.exception.status_code, 500)

    def test_generate_quiz_executes_generation_inner_function_and_json_error_path(self):
        def make_conn():
            return FakeConnection(FakeCursor(fetchall_results=[[{"class_id": "class-1"}]]))

        create_mock = AsyncMock()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        async def run_success():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=make_conn(),
            ), patch(
                "app.routers.quiz.get_settings",
                return_value=SimpleNamespace(llm_model="test-model"),
            ), patch(
                "app.routers.quiz.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.routers.quiz.extract_chat_completion_text",
                return_value=json.dumps(
                    {
                        "quiz_name": "Quiz",
                        "questions": [make_question().model_dump()],
                    }
                ),
            ), patch(
                "app.routers.quiz.with_llm_retry_async",
                side_effect=fake_retry,
            ), patch(
                "app.routers.quiz.pg_service.save_quiz",
                return_value={"quiz_id": "quiz-1", "name": "Quiz"},
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty="medium",
                    num_questions=1,
                )

        result = asyncio.run(run_success())
        self.assertEqual(result.questions[0].question, "What is SQL?")
        self.assertFalse(result.was_summarized)

        async def run_bad_json():
            with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg_db._get_conn",
                return_value=make_conn(),
            ), patch(
                "app.routers.quiz.get_settings",
                return_value=SimpleNamespace(llm_model="test-model"),
            ), patch(
                "app.routers.quiz.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.routers.quiz.extract_chat_completion_text",
                return_value="not-json",
            ), patch(
                "app.routers.quiz.with_llm_retry_async",
                side_effect=fake_retry,
            ):
                return await quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as bad_json:
            asyncio.run(run_bad_json())
        self.assertEqual(bad_json.exception.status_code, 500)

    def test_generate_quiz_summary_and_outer_error_paths(self):
        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        summary_client = SimpleNamespace()
        quiz_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))

        with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="x" * 13001), patch(
            "app.services.pg_db._get_conn",
            return_value=FakeConnection(FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])),
        ), patch(
            "app.routers.quiz.get_settings",
            return_value=SimpleNamespace(llm_model="test-model"),
        ), patch(
            "app.routers.quiz.get_llm_client",
            side_effect=[summary_client, quiz_client],
        ), patch(
            "app.routers.quiz.maybe_truncate_or_summarize",
            return_value="summary text",
        ), patch(
            "app.routers.quiz.extract_chat_completion_text",
            return_value=json.dumps({"quiz_name": "Quiz", "questions": [make_question().model_dump()]}),
        ), patch(
            "app.routers.quiz.with_llm_retry_async",
            side_effect=fake_retry,
        ), patch(
            "app.routers.quiz.pg_service.save_quiz",
            side_effect=RuntimeError("save failed"),
        ):
            result = asyncio.run(
                quiz.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=None,
                    difficulty="easy",
                    num_questions=1,
                )
            )
        self.assertTrue(result.was_summarized)
        self.assertEqual(result.source_text_length, len("summary text"))

        with patch("app.routers.quiz.pg_service.get_files_text_content", return_value="Short source"), patch(
            "app.services.pg_db._get_conn",
            return_value=FakeConnection(FakeCursor(fetchall_results=[[{"class_id": "class-1"}]])),
        ), patch(
            "app.routers.quiz.get_settings",
            side_effect=RuntimeError("settings boom"),
        ):
            with self.assertRaises(HTTPException) as outer_error:
                asyncio.run(
                    quiz.generate_quiz(
                        file_ids=["file-1"],
                        bloom_levels=["remember"],
                        difficulty=None,
                        num_questions=1,
                    )
                )
        self.assertEqual(outer_error.exception.status_code, 500)

    def test_quiz_static_metadata_endpoints(self):
        self.assertEqual(self.client.get("/quiz/bloom-levels").status_code, 200)
        self.assertEqual(self.client.get("/quiz/difficulties").status_code, 200)

    def test_quiz_list_and_detail_routes(self):
        with patch("app.routers.quiz.pg_service.get_quizzes_by_class", return_value=[{"id": "quiz-1"}]):
            listed = self.client.get("/quiz/list", params={"class_id": "class-1"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)

        with patch("app.routers.quiz.pg_service.get_quizzes_by_class", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/quiz/list", params={"class_id": "class-1"}).status_code, 500)

        with patch("app.routers.quiz.pg_service.get_quiz_by_id", return_value={"id": "quiz-1"}):
            self.assertEqual(self.client.get("/quiz/quiz-1").status_code, 200)

        with patch("app.routers.quiz.pg_service.get_quiz_by_id", side_effect=NotFoundError("Quiz not found")):
            self.assertEqual(self.client.get("/quiz/quiz-1").status_code, 404)

        with patch("app.routers.quiz.pg_service.get_quiz_by_id", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/quiz/quiz-1").status_code, 500)

    def test_create_update_delete_quiz_routes(self):
        payload = {"questions": [make_question().model_dump()], "name": "Quiz", "file_ids": ["file-1"], "class_id": "class-1"}

        with patch("app.routers.quiz.pg_service.save_quiz", return_value={"quiz_id": "quiz-1"}):
            created = self.client.post("/quiz/", json=payload)
        self.assertEqual(created.status_code, 200)

        self.assertEqual(self.client.post("/quiz/", json={"questions": []}).status_code, 400)

        with patch("app.routers.quiz.pg_service.save_quiz", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.post("/quiz/", json=payload).status_code, 500)

        with patch("app.routers.quiz.pg_service.update_quiz", return_value={"quiz_id": "quiz-1"}):
            updated = self.client.put("/quiz/quiz-1", json={"questions": [make_question().model_dump()]})
        self.assertEqual(updated.status_code, 200)

        self.assertEqual(self.client.put("/quiz/quiz-1", json={}).status_code, 400)

        with patch("app.routers.quiz.pg_service.update_quiz", side_effect=NotFoundError("Quiz not found")):
            self.assertEqual(self.client.put("/quiz/quiz-1", json={"questions": []}).status_code, 404)

        with patch("app.routers.quiz.pg_service.update_quiz", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.put("/quiz/quiz-1", json={"questions": []}).status_code, 500)

        with patch("app.routers.quiz.pg_service.delete_quiz", return_value={"message": "deleted"}):
            self.assertEqual(self.client.delete("/quiz/quiz-1").status_code, 200)

        with patch("app.routers.quiz.pg_service.delete_quiz", side_effect=NotFoundError("Quiz not found")):
            self.assertEqual(self.client.delete("/quiz/quiz-1").status_code, 404)

        with patch("app.routers.quiz.pg_service.delete_quiz", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.delete("/quiz/quiz-1").status_code, 500)

    def test_submit_and_results_routes(self):
        with patch("app.routers.quiz.pg_service.submit_quiz_result", return_value={"submission_id": "sub-1"}):
            ok = self.client.post(
                "/quiz/quiz-1/submit",
                json={"answers": [], "score": 1, "total_questions": 1},
            )
        self.assertEqual(ok.status_code, 200)

        self.assertEqual(
            self.client.post("/quiz/quiz-1/submit", json={"answers": []}).status_code,
            400,
        )

        with patch("app.routers.quiz.pg_service.submit_quiz_result", side_effect=RuntimeError("db")):
            self.assertEqual(
                self.client.post("/quiz/quiz-1/submit", json={"answers": [], "score": 1, "total_questions": 1}).status_code,
                500,
            )

        with patch("app.routers.quiz.pg_service.is_user_teacher", return_value=False):
            self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 403)

        with patch("app.routers.quiz.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.quiz.pg_service.get_quiz_submissions",
            return_value=[{"id": "sub-1"}],
        ):
            self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 200)

        with patch("app.routers.quiz.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.quiz.pg_service.get_quiz_submissions",
            side_effect=RuntimeError("db"),
        ):
            self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 500)

        with patch("app.routers.quiz.pg_service.get_student_quiz_submission", return_value=None):
            self.assertEqual(self.client.get("/quiz/quiz-1/my-result").json(), {"submission": None})

        with patch("app.routers.quiz.pg_service.get_student_quiz_submission", return_value={"id": "sub-1"}):
            self.assertEqual(self.client.get("/quiz/quiz-1/my-result").json()["submission"]["id"], "sub-1")

        with patch("app.routers.quiz.pg_service.get_student_quiz_submission", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/quiz/quiz-1/my-result").status_code, 500)

        with patch("app.routers.quiz.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.quiz.pg_service.get_quiz_submissions",
            side_effect=HTTPException(status_code=418, detail="teapot"),
        ):
            self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 418)

    def test_generate_feedback_route(self):
        payload = {
            "quiz_name": "Quiz",
            "score": 1,
            "total_questions": 2,
            "percentage": 50,
            "bloom_summary": [],
            "questions": [],
        }

        self.assertEqual(self.client.post("/quiz/quiz-1/feedback", json={"score": 1}).status_code, 400)

        with patch("app.routers.quiz.generate_quiz_feedback_text", AsyncMock(return_value="Keep studying")):
            ok = self.client.post("/quiz/quiz-1/feedback", json=payload)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["feedback"], "Keep studying")

        with patch("app.routers.quiz.generate_quiz_feedback_text", AsyncMock(side_effect=RuntimeError("boom"))):
            failed = self.client.post("/quiz/quiz-1/feedback", json=payload)
        self.assertEqual(failed.status_code, 500)

        with patch("app.routers.quiz.generate_quiz_feedback_text", AsyncMock(side_effect=HTTPException(status_code=418, detail="teapot"))):
            teapot = self.client.post("/quiz/quiz-1/feedback", json=payload)
        self.assertEqual(teapot.status_code, 418)



