import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.agents.schemas import ExamGenerationResponse, ExamQuestion
from app.routers import exam
from app.services.exceptions import AlreadySubmittedError, NotFoundError, NotReleasedError, PermissionDeniedError
from tests.support import build_app, with_auth


def make_exam_response():
    return ExamGenerationResponse(
        exam_id="exam-1",
        exam_name="Database Exam",
        questions=[],
        pdf_path="/tmp/exam-1.pdf",
        warnings=[],
        review_score=95,
    )


def make_question_dict():
    return {
        "question_id": "q-1",
        "question_type": "multiple_choice",
        "bloom_level": "remember",
        "question_text": "What is SQL?",
        "choices": ["A", "B", "C", "D"],
        "correct_answer_index": 1,
        "marks": 1,
        "marking_scheme": [],
        "rationale": "Basic recall",
        "model_answer": None,
        "image_description": None,
        "image_path": None,
        "source_chunk_ids": [],
    }


class ExamApiTests(unittest.TestCase):
    def setUp(self):
        app = build_app(exam.router)
        with_auth(app, exam.get_current_user, {"user_id": "teacher-1", "email": "teacher@example.com"})
        self.client = TestClient(app)

    def test_grade_answer_item_requires_identifier(self):
        with self.assertRaises(Exception):
            exam.GradeAnswerItem(marks_earned=1)

    def test_generate_exam_success(self):
        with patch("app.services.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(return_value=make_exam_response())):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exam_id"], "exam-1")

    def test_generate_exam_value_error(self):
        with patch("app.services.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(side_effect=ValueError("bad input"))):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 400)

    def test_generate_exam_unexpected_error(self):
        with patch("app.services.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(side_effect=RuntimeError("boom"))):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 500)

    def test_generate_questions_only_success(self):
        with patch("app.services.exam_workflow_service.run_exam_generation", AsyncMock(return_value=make_exam_response())):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 200)

    def test_generate_questions_only_value_error(self):
        with patch("app.services.exam_workflow_service.run_exam_generation", AsyncMock(side_effect=ValueError("bad input"))):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 400)

    def test_generate_questions_only_unexpected_error(self):
        with patch("app.services.exam_workflow_service.run_exam_generation", AsyncMock(side_effect=RuntimeError("boom"))):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 500)

    def test_regenerate_pdf_success(self):
        with patch("app.services.exam_workflow_service.generate_exam_pdf", AsyncMock(return_value="/tmp/exam-1.pdf")):
            response = self.client.post(
                "/exam/exam-1/regenerate-pdf",
                json={"questions": [make_question_dict()], "exam_name": "Database Exam"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pdf_path"], "/tmp/exam-1.pdf")

    def test_regenerate_pdf_failure(self):
        with patch("app.services.exam_workflow_service.generate_exam_pdf", AsyncMock(side_effect=RuntimeError("pdf boom"))):
            response = self.client.post(
                "/exam/exam-1/regenerate-pdf",
                json={"questions": [make_question_dict()], "exam_name": "Database Exam"},
            )

        self.assertEqual(response.status_code, 500)

    def test_download_exam_pdf_handles_missing_and_success(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch("app.routers.exam.PDF_DIR", tmpdir):
            missing = self.client.get("/exam/exam-1/pdf")
            self.assertEqual(missing.status_code, 404)

            pdf_path = tempfile.NamedTemporaryFile(dir=tmpdir, suffix=".pdf", delete=False)
            pdf_path.write(b"%PDF-1.4")
            pdf_path.close()
            import os

            os.replace(pdf_path.name, os.path.join(tmpdir, "exam-1.pdf"))
            response = self.client.get("/exam/exam-1/pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")

    def test_get_exam_image_validates_name_and_presence(self):
        forbidden = self.client.get("/exam/exam-1/image/other.png")
        self.assertEqual(forbidden.status_code, 403)

        missing = self.client.get("/exam/exam-1/image/exam-1_missing.png")
        self.assertEqual(missing.status_code, 404)

        with tempfile.TemporaryDirectory() as tmpdir, patch("app.routers.exam.IMAGES_DIR", tmpdir):
            path = Path(tmpdir) / "exam-1_chart.png"
            with open(path, "wb") as handle:
                handle.write(b"png")
            response = self.client.get("/exam/exam-1/image/exam-1_chart.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_static_exam_metadata_endpoints(self):
        self.assertEqual(self.client.get("/exam/difficulties").status_code, 200)
        self.assertEqual(self.client.get("/exam/question-types").status_code, 200)

    def test_get_exams_list_success_and_failure(self):
        with patch("app.routers.exam.pg_service.get_exams_by_class", return_value=[{"id": "exam-1"}]):
            ok = self.client.get("/exam/list", params={"class_id": "class-1"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["total"], 1)

        with patch("app.routers.exam.pg_service.get_exams_by_class", side_effect=RuntimeError("db")):
            failed = self.client.get("/exam/list", params={"class_id": "class-1"})
        self.assertEqual(failed.status_code, 500)

    def test_get_exam_handles_roles_and_errors(self):
        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.get_exam_by_id",
            return_value={"id": "exam-1"},
        ):
            ok = self.client.get("/exam/exam-1")
        self.assertEqual(ok.status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=False), patch(
            "app.routers.exam.pg_service.get_exam_by_id",
            return_value={"id": "exam-1"},
        ) as get_exam_by_id:
            self.client.get("/exam/exam-1")
        self.assertFalse(get_exam_by_id.call_args.args[2])

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.get_exam_by_id",
            side_effect=PermissionDeniedError("forbidden"),
        ):
            forbidden = self.client.get("/exam/exam-1")
        self.assertEqual(forbidden.status_code, 403)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.get_exam_by_id",
            side_effect=NotFoundError("not found"),
        ):
            missing = self.client.get("/exam/exam-1")
        self.assertEqual(missing.status_code, 404)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.get_exam_by_id",
            side_effect=RuntimeError("boom"),
        ):
            failed = self.client.get("/exam/exam-1")
        self.assertEqual(failed.status_code, 500)

    def test_update_delete_and_publish_exam_routes(self):
        payload = {"title": "Updated", "questions": [make_question_dict()]}

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=False):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 403)
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 403)
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 403)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.update_exam",
            return_value={"id": "exam-1"},
        ):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.update_exam",
            side_effect=NotFoundError("not found"),
        ):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 404)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.delete_exam",
            return_value={"message": "deleted"},
        ):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.delete_exam",
            side_effect=NotFoundError("not found"),
        ):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 404)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.publish_exam",
            return_value={"id": "exam-1", "is_published": True},
        ):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 200)

    def test_start_and_submit_exam_routes(self):
        with patch("app.routers.exam.pg_service.start_exam_submission", return_value={"submission_id": "sub-1", "started_at": "now", "attempt_no": 1, "duration_minutes": 30}):
            started = self.client.post("/exam/exam-1/start")
        self.assertEqual(started.status_code, 200)

        with patch("app.routers.exam.pg_service.start_exam_submission", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 404)

        with patch("app.routers.exam.pg_service.start_exam_submission", side_effect=NotReleasedError()):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 403)

        with patch("app.routers.exam.pg_service.submit_exam", return_value={"submission_id": "sub-1"}):
            submitted = self.client.post("/exam/submission/sub-1/submit", json={"answers": []})
        self.assertEqual(submitted.status_code, 200)

        with patch("app.routers.exam.pg_service.submit_exam", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 404)

        with patch("app.routers.exam.pg_service.submit_exam", side_effect=AlreadySubmittedError()):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 400)

    def test_submission_listing_and_manual_grading_routes(self):
        with patch("app.routers.exam.pg_service.get_student_exam_submissions", return_value=[{"id": "sub-1"}]):
            mine = self.client.get("/exam/exam-1/my-submissions")
        self.assertEqual(mine.status_code, 200)

        with patch("app.routers.exam.pg_service.get_student_exam_submissions", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/exam/exam-1/my-submissions").status_code, 500)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=False):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 403)
            self.assertEqual(self.client.put("/exam/submission/sub-1/grade", json={"answers_grades": []}).status_code, 403)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.get_exam_submissions",
            return_value=[{"id": "sub-1"}],
        ):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.grade_exam_submission",
            return_value={"id": "sub-1"},
        ):
            ok = self.client.put(
                "/exam/submission/sub-1/grade",
                json={"answers_grades": [{"answer_id": "answer-1", "marks_earned": 1}], "teacher_comment": "ok"},
            )
        self.assertEqual(ok.status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.grade_exam_submission",
            side_effect=NotFoundError("not found"),
        ):
            missing = self.client.put(
                "/exam/submission/sub-1/grade",
                json={"answers_grades": [{"answer_id": "answer-1", "marks_earned": 1}]},
            )
        self.assertEqual(missing.status_code, 404)

    def test_ai_grade_submission_routes(self):
        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=False):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 403)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value=None,
        ):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 404)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value={"answers": []},
        ):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 400)

        submission = {
            "answers": [
                {
                    "id": "answer-1",
                    "exam_question_id": "eq-1",
                    "answer_text": "Because of blocking",
                    "marks_earned": 0,
                    "teacher_feedback": "",
                    "is_correct": False,
                    "question_snapshot": {
                        "question_type": "short_answer",
                        "question_text": "Explain 2PC",
                        "marks": 3,
                        "model_answer": "It blocks participants",
                        "marking_scheme": [],
                    },
                }
            ]
        }
        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value=submission,
        ), patch(
            "app.services.exam_workflow_service.ai_grade_answer",
            AsyncMock(return_value={"marks_earned": 2, "feedback": "good", "is_correct": False}),
        ), patch(
            "app.services.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.exam_workflow_service.persist_ai_grade_exam_submission",
            return_value={"submission_id": "sub-1"},
        ):
            response = self.client.post("/exam/submission/sub-1/ai-grade")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["submission"]["submission_id"], "sub-1")

    def test_exam_additional_error_paths(self):
        payload = {"title": "Updated", "questions": [make_question_dict()]}

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.update_exam",
            side_effect=Exception("boom"),
        ):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 500)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.delete_exam",
            side_effect=Exception("boom"),
        ):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 500)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.publish_exam",
            return_value={"id": "exam-1", "is_published": False},
        ):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": False}).status_code, 200)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.publish_exam",
            side_effect=NotFoundError("not found"),
        ):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 404)

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.routers.exam.pg_service.publish_exam",
            side_effect=Exception("boom"),
        ):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 500)

        with patch("app.routers.exam.pg_service.start_exam_submission", side_effect=RuntimeError("boom")):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 500)

        with patch("app.routers.exam.pg_service.submit_exam", side_effect=RuntimeError("boom")):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 500)

        with patch("app.routers.exam.pg_service.get_exam_submissions", side_effect=Exception("boom")), patch(
            "app.routers.exam.pg_service.is_user_teacher",
            return_value=True,
        ):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 500)

        with patch("app.routers.exam.pg_service.get_student_exam_submissions", side_effect=Exception("boom")):
            self.assertEqual(self.client.get("/exam/exam-1/my-submissions").status_code, 500)

        with patch("app.routers.exam.pg_service.grade_exam_submission", return_value={"id": "sub-1"}), patch(
            "app.routers.exam.pg_service.is_user_teacher",
            return_value=True,
        ):
            result = asyncio.run(
                exam.grade_submission(
                    "sub-1",
                    exam.GradeSubmissionRequest(answers_grades=None, teacher_comment="ok"),
                    {"user_id": "teacher-1"},
                )
            )
        self.assertEqual(result["submission"]["id"], "sub-1")

        with patch("app.routers.exam.pg_service.grade_exam_submission", side_effect=Exception("boom")), patch(
            "app.routers.exam.pg_service.is_user_teacher",
            return_value=True,
        ):
            self.assertEqual(self.client.put("/exam/submission/sub-1/grade", json={"teacher_comment": "ok"}).status_code, 500)

    def test_ai_grade_submission_additional_paths(self):
        mcq_only = {
            "answers": [
                {
                    "id": "answer-1",
                    "exam_question_id": "eq-1",
                    "answer_text": "",
                    "marks_earned": 1,
                    "teacher_feedback": "",
                    "is_correct": True,
                    "question_snapshot": {
                        "question_type": "multiple_choice",
                        "question_text": "",
                        "choices": ["A", "B"],
                        "marks": 1,
                    },
                }
            ]
        }
        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value=mcq_only,
        ), patch(
            "app.services.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.exam_workflow_service.persist_ai_grade_exam_submission",
            return_value={"submission_id": "sub-1"},
        ):
            response = self.client.post("/exam/submission/sub-1/ai-grade")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["graded_answers"][0]["ai_graded"])

        mixed_submission = {
            "answers": [
                {
                    "id": "answer-1",
                    "exam_question_id": "eq-1",
                    "answer_text": "text",
                    "marks_earned": 0,
                    "teacher_feedback": "",
                    "is_correct": False,
                    "question_snapshot": {
                        "question_type": "multiple_choice",
                        "question": "Fallback question text",
                        "choices": [],
                        "marks": 2,
                    },
                }
            ]
        }
        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value=mixed_submission,
        ), patch(
            "app.services.exam_workflow_service.ai_grade_answer",
            AsyncMock(side_effect=RuntimeError("provider failed")),
        ), patch(
            "app.services.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.exam_workflow_service.persist_ai_grade_exam_submission",
            return_value={"submission_id": "sub-1"},
        ):
            response = self.client.post("/exam/submission/sub-1/ai-grade")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please grade manually", response.json()["graded_answers"][0]["teacher_feedback"])

        with patch("app.routers.exam.pg_service.is_user_teacher", return_value=True), patch(
            "app.services.exam_workflow_service.get_submission_with_answers",
            return_value=mixed_submission,
        ), patch(
            "app.services.exam_workflow_service.ai_grade_answer",
            AsyncMock(return_value={"marks_earned": 1, "feedback": "ok", "is_correct": True}),
        ), patch(
            "app.services.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(side_effect=RuntimeError("overall failed")),
        ):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 500)

