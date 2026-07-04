import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.routers import quiz
from app.services.core.exceptions import NotFoundError, ServiceError
from app.utils.aqg import MultipleChoice
from tests.support import FakeConnection, FakeCursor, fake_llm_retry, make_chat_client, make_settings, start_patches, with_auth


def make_question():
    return MultipleChoice(
        bloom_level="remember",
        question="What is SQL?",
        choices=["A", "B", "C", "D"],
        answer_index=1,
        rationale="Basic recall",
    )


def class_lookup_conn(rows=None):
    return FakeConnection(FakeCursor(fetchall_results=rows or [[{"class_id": "class-1"}]]))


def quiz_settings():
    return make_settings(llm_model="test-model")


class QuizApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.exception_handler(ServiceError)
        async def service_error_handler(request: Request, exc: ServiceError):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

        app.include_router(quiz.router, prefix="/quiz")
        with_auth(app, quiz.get_current_user, {"user_id": "teacher-1", "email": "teacher@example.com"})
        self.user = {"user_id": "teacher-1", "email": "teacher@example.com"}

        self.client = TestClient(app)
        (
            self.get_quizzes_by_class,
            self.get_quiz_by_id,
            self.save_quiz,
            self.update_quiz,
            self.delete_quiz,
            self.submit_quiz_result,
            self.get_quiz_submissions,
            self.get_student_quiz_submission,
        ) = start_patches(
            self,
            patch("app.routers.quiz.pg_quiz_service.get_quizzes_by_class"),
            patch("app.routers.quiz.pg_quiz_service.get_quiz_by_id"),
            patch("app.routers.quiz.pg_quiz_service.save_quiz"),
            patch("app.routers.quiz.pg_quiz_service.update_quiz"),
            patch("app.routers.quiz.pg_quiz_service.delete_quiz"),
            patch("app.routers.quiz.pg_quiz_service.submit_quiz_result"),
            patch("app.routers.quiz.pg_quiz_service.get_quiz_submissions"),
            patch("app.routers.quiz.pg_quiz_service.get_student_quiz_submission"),
        )
        start_patches(
            self,
            patch("app.routers.quiz.is_user_teacher", return_value=True),
            patch("app.routers.quiz.pg_service.is_user_student", return_value=True),
            patch("app.routers.quiz.pg_service.can_access_class", return_value=True),
            patch("app.routers.quiz.pg_service.can_access_quiz", return_value=True),
            patch("app.routers.quiz.pg_service.can_manage_documents", return_value=True),
            patch("app.routers.quiz.redis_cache.get_settings", return_value=make_settings()),
        )

    async def generate_quiz(self, **kwargs):
        return await quiz.generate_quiz(user=self.user, **kwargs)

    def generation_patches(self, source_text="Short source", *, retry_return=None, retry_side_effect=None):
        stack = ExitStack()
        stack.enter_context(
            patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value=source_text)
        )
        stack.enter_context(patch("app.services.pg.pg_db._get_conn", return_value=class_lookup_conn()))
        stack.enter_context(patch("app.services.assessment.quiz_generation_service.get_settings", return_value=quiz_settings()))
        retry_kwargs = {"side_effect": retry_side_effect} if retry_side_effect is not None else {"return_value": retry_return}
        stack.enter_context(patch("app.services.assessment.quiz_generation_service.with_llm_retry_async", **retry_kwargs))
        stack.enter_context(
            patch("app.services.assessment.quiz_generation_service.save_quiz", return_value={"quiz_id": "quiz-1", "name": "Quiz"})
        )
        return stack

    def route_status(self, method, path, expected_status, *, service_mock=None, side_effect=None, return_value=None, **kwargs):
        if service_mock is not None:
            service_mock.side_effect = side_effect
            if return_value is not None:
                service_mock.return_value = return_value
        response = getattr(self.client, method)(path, **kwargs)
        self.assertEqual(response.status_code, expected_status)
        if service_mock is not None:
            service_mock.side_effect = None
        return response

    def test_generate_quiz_happy_path_without_summary(self):
        async def run():
            with self.generation_patches(retry_return={"quiz_name": "Quiz", "questions": [make_question()]}):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        response = asyncio.run(run())
        self.assertEqual(response.questions[0].question, "What is SQL?")
        self.assertFalse(response.was_summarized)

    def test_generate_quiz_uses_summary_path_for_long_source(self):
        long_text = "x" * 13000

        async def run():
            with self.generation_patches(
                long_text,
                retry_side_effect=["summary", {"quiz_name": "Quiz", "questions": [make_question()]}],
            ):
                return await self.generate_quiz(
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
            return await self.generate_quiz(file_ids=[], bloom_levels=None, difficulty=None, num_questions=1)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run_empty_files())
        self.assertEqual(ctx.exception.status_code, 400)

        async def run_missing_text():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value=""), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ):
                return await self.generate_quiz(file_ids=["file-1"], bloom_levels=None, difficulty=None, num_questions=1)

        with self.assertRaises(HTTPException) as missing_text:
            asyncio.run(run_missing_text())
        self.assertEqual(missing_text.exception.status_code, 400)

        async def run_bad_count():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ):
                return await self.generate_quiz(file_ids=["file-1"], bloom_levels=None, difficulty=None, num_questions=100)

        with self.assertRaises(HTTPException) as bad_count:
            asyncio.run(run_bad_count())
        self.assertEqual(bad_count.exception.status_code, 400)

        async def run_difficulty_only():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="   "), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=None,
                    difficulty="easy",
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as blank_text:
            asyncio.run(run_difficulty_only())
        self.assertEqual(blank_text.exception.status_code, 400)

        async def run_bad_class_lookup():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                side_effect=RuntimeError("db down"),
            ):
                return await self.generate_quiz(
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
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", side_effect=RuntimeError("missing")):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as missing_source:
            asyncio.run(run_missing_source())
        self.assertEqual(missing_source.exception.status_code, 404)

        async def run_invalid_class():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn([[]]),
            ):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as invalid_class:
            asyncio.run(run_invalid_class())
        self.assertEqual(invalid_class.exception.status_code, 400)

        fake_client = make_chat_client(object())

        async def run_empty_provider():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_settings",
                return_value=quiz_settings(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.services.assessment.quiz_generation_service.extract_chat_completion_text",
                return_value="",
            ), patch(
                "app.services.assessment.quiz_generation_service.with_llm_retry_async",
                side_effect=fake_llm_retry,
            ):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as empty_provider:
            asyncio.run(run_empty_provider())
        self.assertEqual(empty_provider.exception.status_code, 500)

    def test_generate_quiz_executes_generation_inner_function_and_json_error_path(self):
        fake_client = make_chat_client(object())

        async def run_success():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_settings",
                return_value=quiz_settings(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.services.assessment.quiz_generation_service.extract_chat_completion_text",
                return_value=json.dumps(
                    {
                        "quiz_name": "Quiz",
                        "questions": [make_question().model_dump()],
                    }
                ),
            ), patch(
                "app.services.assessment.quiz_generation_service.with_llm_retry_async",
                side_effect=fake_llm_retry,
            ), patch(
                "app.services.assessment.quiz_generation_service.save_quiz",
                return_value={"quiz_id": "quiz-1", "name": "Quiz"},
            ):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty="medium",
                    num_questions=1,
                )

        result = asyncio.run(run_success())
        self.assertEqual(result.questions[0].question, "What is SQL?")
        self.assertFalse(result.was_summarized)

        async def run_bad_json():
            with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
                "app.services.pg.pg_db._get_conn",
                return_value=class_lookup_conn(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_settings",
                return_value=quiz_settings(),
            ), patch(
                "app.services.assessment.quiz_generation_service.get_llm_client",
                return_value=fake_client,
            ), patch(
                "app.services.assessment.quiz_generation_service.extract_chat_completion_text",
                return_value="not-json",
            ), patch(
                "app.services.assessment.quiz_generation_service.with_llm_retry_async",
                side_effect=fake_llm_retry,
            ):
                return await self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=["remember"],
                    difficulty=None,
                    num_questions=1,
                )

        with self.assertRaises(HTTPException) as bad_json:
            asyncio.run(run_bad_json())
        self.assertEqual(bad_json.exception.status_code, 500)

    def test_generate_quiz_summary_and_outer_error_paths(self):
        summary_client = object()
        quiz_client = make_chat_client(object())

        with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="x" * 13001), patch(
            "app.services.pg.pg_db._get_conn",
            return_value=class_lookup_conn(),
        ), patch(
            "app.services.assessment.quiz_generation_service.get_settings",
            return_value=quiz_settings(),
        ), patch(
            "app.services.assessment.quiz_generation_service.get_llm_client",
            side_effect=[summary_client, quiz_client],
        ), patch(
            "app.services.assessment.quiz_generation_service.maybe_truncate_or_summarize",
            return_value="summary text",
        ), patch(
            "app.services.assessment.quiz_generation_service.extract_chat_completion_text",
            return_value=json.dumps({"quiz_name": "Quiz", "questions": [make_question().model_dump()]}),
        ), patch(
            "app.services.assessment.quiz_generation_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ), patch(
            "app.services.assessment.quiz_generation_service.save_quiz",
            side_effect=RuntimeError("save failed"),
        ):
            result = asyncio.run(
                self.generate_quiz(
                    file_ids=["file-1"],
                    bloom_levels=None,
                    difficulty="easy",
                    num_questions=1,
                )
            )
        self.assertTrue(result.was_summarized)
        self.assertEqual(result.source_text_length, len("summary text"))

        with patch("app.services.assessment.quiz_generation_service.get_files_text_content", return_value="Short source"), patch(
            "app.services.pg.pg_db._get_conn",
            return_value=class_lookup_conn(),
        ), patch(
            "app.services.assessment.quiz_generation_service.get_settings",
            side_effect=RuntimeError("settings boom"),
        ):
            with self.assertRaises(HTTPException) as outer_error:
                asyncio.run(
                    self.generate_quiz(
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
        self.get_quizzes_by_class.return_value = [{"id": "quiz-1"}]
        listed = self.client.get("/quiz/list", params={"class_id": "class-1"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)

        self.route_status(
            "get",
            "/quiz/list",
            500,
            service_mock=self.get_quizzes_by_class,
            side_effect=RuntimeError("db"),
            params={"class_id": "class-1"},
        )

        self.route_status("get", "/quiz/quiz-1", 200, service_mock=self.get_quiz_by_id, return_value={"id": "quiz-1"})

        self.route_status("get", "/quiz/quiz-1", 404, service_mock=self.get_quiz_by_id, side_effect=NotFoundError("Quiz not found"))
        self.route_status("get", "/quiz/quiz-1", 500, service_mock=self.get_quiz_by_id, side_effect=RuntimeError("db"))

    def test_quiz_list_and_detail_use_cache_when_enabled(self):
        with patch(
            "app.routers.quiz.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=quiz.redis_cache.CacheResult(
                    {"message": "Fetched quizzes", "quizzes": [{"id": "quiz-1"}], "total": 1},
                    "MISS",
                    "quiz:list",
                )
            ),
        ) as get_or_set:
            listed = self.client.get("/quiz/list", params={"class_id": "class-1"})

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.headers["X-Redis-Cache"], "MISS")
        self.assertEqual(get_or_set.call_args.args[0], "quiz:list")
        self.get_quizzes_by_class.assert_not_called()

        with patch("app.routers.quiz.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.quiz.pg_service.can_access_quiz",
            return_value=True,
        ), patch(
            "app.routers.quiz.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=quiz.redis_cache.CacheResult(
                    {"message": "Fetched quiz", "quiz": {"id": "quiz-1"}},
                    "HIT",
                    "quiz:detail",
                )
            ),
        ) as get_detail:
            detail = self.client.get("/quiz/quiz-1")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.headers["X-Redis-Cache"], "HIT")
        self.assertEqual(get_detail.call_args.args[0], "quiz:detail")
        self.get_quiz_by_id.assert_not_called()

    def test_quiz_detail_skips_cache_when_access_probe_fails(self):
        self.get_quiz_by_id.return_value = {"id": "quiz-1"}
        with patch("app.routers.quiz.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.quiz.pg_service.can_access_quiz",
            side_effect=RuntimeError("access db"),
        ), patch("app.routers.quiz.redis_cache.get_or_set_json_with_status", AsyncMock()) as get_or_set:
            response = self.client.get("/quiz/quiz-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "BYPASS")
        get_or_set.assert_not_called()

    def test_quiz_mutations_invalidate_cache_namespaces(self):
        payload = {"questions": [make_question().model_dump()], "class_id": "class-1"}
        self.save_quiz.return_value = {"quiz_id": "quiz-1"}
        with patch("app.routers.quiz.redis_cache.invalidate_namespaces") as invalidate:
            self.client.post("/quiz/", json=payload)
        invalidate.assert_called_with("quiz:list", "quiz:detail:quiz-1")

        self.update_quiz.return_value = {"quiz_id": "quiz-1"}
        with patch("app.routers.quiz.redis_cache.invalidate_namespaces") as update_invalidate:
            self.client.put("/quiz/quiz-1", json={"questions": [make_question().model_dump()]})
        update_invalidate.assert_called_with("quiz:list", "quiz:detail:quiz-1")

        self.delete_quiz.return_value = {"message": "deleted"}
        with patch("app.routers.quiz.redis_cache.invalidate_namespaces") as delete_invalidate:
            self.client.delete("/quiz/quiz-1")
        delete_invalidate.assert_called_with("quiz:list", "quiz:detail:quiz-1")

    def test_create_update_delete_quiz_routes(self):
        payload = {
            "questions": [make_question().model_dump()],
            "name": "Quiz",
            "file_ids": ["file-1"],
            "class_id": "class-1",
        }

        self.save_quiz.return_value = {"quiz_id": "quiz-1"}
        created = self.client.post("/quiz/", json=payload)
        self.assertEqual(created.status_code, 200)

        self.assertEqual(self.client.post("/quiz/", json={"questions": []}).status_code, 400)
        self.assertEqual(self.client.post("/quiz/", json={"questions": [make_question().model_dump()]}).status_code, 403)

        self.route_status("post", "/quiz/", 500, service_mock=self.save_quiz, side_effect=RuntimeError("db"), json=payload)

        self.update_quiz.return_value = {"quiz_id": "quiz-1"}
        updated = self.client.put("/quiz/quiz-1", json={"questions": [make_question().model_dump()]})
        self.assertEqual(updated.status_code, 200)

        updated_with_files = self.client.put("/quiz/quiz-1", json={"questions": [make_question().model_dump()], "file_ids": ["file-1"]})
        self.assertEqual(updated_with_files.status_code, 200)

        self.assertEqual(self.client.put("/quiz/quiz-1", json={}).status_code, 400)

        self.route_status(
            "put", "/quiz/quiz-1", 404, service_mock=self.update_quiz, side_effect=NotFoundError("Quiz not found"), json={"questions": []}
        )
        self.route_status("put", "/quiz/quiz-1", 500, service_mock=self.update_quiz, side_effect=RuntimeError("db"), json={"questions": []})

        self.delete_quiz.return_value = {"message": "deleted"}
        self.assertEqual(self.client.delete("/quiz/quiz-1").status_code, 200)

        self.route_status("delete", "/quiz/quiz-1", 404, service_mock=self.delete_quiz, side_effect=NotFoundError("Quiz not found"))
        self.route_status("delete", "/quiz/quiz-1", 500, service_mock=self.delete_quiz, side_effect=RuntimeError("db"))

    def test_submit_and_results_routes(self):
        self.submit_quiz_result.return_value = {"submission_id": "sub-1"}
        ok = self.client.post(
            "/quiz/quiz-1/submit",
            json={"answers": [], "score": 1, "total_questions": 1},
        )
        self.assertEqual(ok.status_code, 200)

        self.assertEqual(
            self.client.post("/quiz/quiz-1/submit", json={"answers": []}).status_code,
            400,
        )

        self.route_status(
            "post",
            "/quiz/quiz-1/submit",
            500,
            service_mock=self.submit_quiz_result,
            side_effect=RuntimeError("db"),
            json={"answers": [], "score": 1, "total_questions": 1},
        )

        with patch("app.routers.quiz.is_user_teacher", return_value=False):
            self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 403)

        self.get_quiz_submissions.return_value = [{"id": "sub-1"}]
        self.assertEqual(self.client.get("/quiz/quiz-1/results").status_code, 200)

        self.route_status("get", "/quiz/quiz-1/results", 500, service_mock=self.get_quiz_submissions, side_effect=RuntimeError("db"))

        self.get_student_quiz_submission.return_value = None
        self.assertEqual(self.client.get("/quiz/quiz-1/my-result").json(), {"submission": None})

        self.get_student_quiz_submission.return_value = {"id": "sub-1"}
        self.assertEqual(self.client.get("/quiz/quiz-1/my-result").json()["submission"]["id"], "sub-1")

        self.route_status(
            "get", "/quiz/quiz-1/my-result", 500, service_mock=self.get_student_quiz_submission, side_effect=RuntimeError("db")
        )

        teapot = self.route_status(
            "get",
            "/quiz/quiz-1/results",
            418,
            service_mock=self.get_quiz_submissions,
            side_effect=HTTPException(status_code=418, detail="teapot"),
        )
        self.assertEqual(teapot.json()["detail"], "teapot")

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


