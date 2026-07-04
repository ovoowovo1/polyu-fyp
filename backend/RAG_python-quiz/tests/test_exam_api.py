import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.agents.schemas import ExamGenerationResponse
from app.routers import exam
from app.services.core.exceptions import AlreadySubmittedError, NotFoundError, NotReleasedError, PermissionDeniedError
from tests.support import build_authed_client, make_settings, start_patches


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
        _app, self.client = build_authed_client(
            exam.router,
            exam.get_current_user,
            {"user_id": "teacher-1", "email": "teacher@example.com"},
        )
        start_patches(
            self,
            patch("app.routers.exam.is_user_teacher", return_value=True),
            patch("app.routers.exam.can_access_class", return_value=True),
            patch("app.routers.exam.can_access_exam", return_value=True),
            patch("app.routers.exam.can_manage_documents", return_value=True),
            patch("app.routers.exam.require_submission_owner", return_value=None),
            patch("app.routers.exam.require_submission_teacher", return_value=None),
            patch("app.routers.exam.redis_cache.get_settings", return_value=make_settings()),
        )

    def test_grade_answer_item_requires_identifier(self):
        with self.assertRaises(Exception):
            exam.GradeAnswerItem(marks_earned=1)

    def test_generate_exam_success(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(return_value=make_exam_response())):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exam_id"], "exam-1")

    def test_generate_exam_value_error(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(side_effect=ValueError("bad input"))):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 400)

    def test_generate_exam_unexpected_error(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(side_effect=RuntimeError("boom"))):
            response = self.client.post("/exam/generate", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 500)

    def test_generate_questions_only_success(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation", AsyncMock(return_value=make_exam_response())):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 200)

    def test_generate_questions_only_value_error(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation", AsyncMock(side_effect=ValueError("bad input"))):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 400)

    def test_generate_questions_only_unexpected_error(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation", AsyncMock(side_effect=RuntimeError("boom"))):
            response = self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})

        self.assertEqual(response.status_code, 500)

    def test_regenerate_pdf_success(self):
        with patch("app.services.assessment.exam_workflow_service.generate_exam_pdf", AsyncMock(return_value="/tmp/exam-1.pdf")):
            response = self.client.post(
                "/exam/exam-1/regenerate-pdf",
                json={"questions": [make_question_dict()], "exam_name": "Database Exam"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pdf_path"], "/tmp/exam-1.pdf")

    def test_regenerate_pdf_failure(self):
        with patch("app.services.assessment.exam_workflow_service.generate_exam_pdf", AsyncMock(side_effect=RuntimeError("pdf boom"))):
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
        with patch("app.routers.exam.get_exams_by_class", return_value=[{"id": "exam-1"}]):
            ok = self.client.get("/exam/list", params={"class_id": "class-1"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["total"], 1)

        with patch("app.routers.exam.get_exams_by_class", side_effect=RuntimeError("db")):
            failed = self.client.get("/exam/list", params={"class_id": "class-1"})
        self.assertEqual(failed.status_code, 500)

    def test_get_exams_list_uses_cache_when_enabled(self):
        with patch(
            "app.routers.exam.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=exam.redis_cache.CacheResult(
                    {"message": "Fetched exams", "exams": [{"id": "exam-1"}], "total": 1},
                    "MISS",
                    "exam:list",
                )
            ),
        ) as get_or_set, patch("app.routers.exam.get_exams_by_class") as get_exams:
            response = self.client.get("/exam/list", params={"class_id": "class-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "MISS")
        self.assertEqual(get_or_set.call_args.args[0], "exam:list")
        get_exams.assert_not_called()

    def test_get_exam_handles_roles_and_errors(self):
        with patch("app.routers.exam.get_exam_by_id", return_value={"id": "exam-1"}):
            ok = self.client.get("/exam/exam-1")
        self.assertEqual(ok.status_code, 200)

        with patch("app.routers.exam.is_user_teacher", return_value=False), patch(
            "app.routers.exam.get_exam_by_id",
            return_value={"id": "exam-1"},
        ) as get_exam_by_id:
            self.client.get("/exam/exam-1")
        self.assertFalse(get_exam_by_id.call_args.args[2])

        with patch("app.routers.exam.get_exam_by_id", side_effect=PermissionDeniedError("forbidden")):
            forbidden = self.client.get("/exam/exam-1")
        self.assertEqual(forbidden.status_code, 403)

        with patch("app.routers.exam.get_exam_by_id", side_effect=NotFoundError("not found")):
            missing = self.client.get("/exam/exam-1")
        self.assertEqual(missing.status_code, 404)

        with patch("app.routers.exam.get_exam_by_id", side_effect=RuntimeError("boom")):
            failed = self.client.get("/exam/exam-1")
        self.assertEqual(failed.status_code, 500)

    def test_get_exam_uses_cache_with_effective_include_answers(self):
        with patch("app.routers.exam.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.exam.can_access_exam",
            return_value=True,
        ), patch(
            "app.routers.exam.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=exam.redis_cache.CacheResult(
                    {"message": "Fetched exam", "exam": {"id": "exam-1"}},
                    "HIT",
                    "exam:detail",
                )
            ),
        ) as get_or_set, patch("app.routers.exam.get_exam_by_id") as get_exam_by_id:
            response = self.client.get("/exam/exam-1", params={"include_answers": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "HIT")
        self.assertEqual(get_or_set.call_args.args[0], "exam:detail")
        self.assertTrue(get_or_set.call_args.args[1]["include_answers"])
        get_exam_by_id.assert_not_called()

        with patch("app.routers.exam.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.exam.is_user_teacher",
            return_value=False,
        ), patch("app.routers.exam.can_access_exam", return_value=True), patch(
            "app.routers.exam.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=exam.redis_cache.CacheResult(
                    {"message": "Fetched exam", "exam": {"id": "exam-1"}},
                    "HIT",
                    "exam:detail",
                )
            ),
        ) as student_get_or_set:
            student_response = self.client.get("/exam/exam-1", params={"include_answers": True})

        self.assertEqual(student_response.status_code, 200)
        self.assertFalse(student_get_or_set.call_args.args[1]["include_answers"])

    def test_get_exam_skips_cache_when_access_probe_fails(self):
        with patch("app.routers.exam.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.exam.can_access_exam",
            side_effect=RuntimeError("access db"),
        ), patch("app.routers.exam.get_exam_by_id", return_value={"id": "exam-1"}), patch(
            "app.routers.exam.redis_cache.get_or_set_json_with_status",
            AsyncMock(),
        ) as get_or_set:
            response = self.client.get("/exam/exam-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "BYPASS")
        get_or_set.assert_not_called()

    def test_exam_mutations_invalidate_cache_namespaces(self):
        with patch("app.services.assessment.exam_workflow_service.run_exam_generation_with_pdf", AsyncMock(return_value=make_exam_response())), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as generate_invalidate:
            self.client.post("/exam/generate", json={"file_ids": ["file-1"]})
        generate_invalidate.assert_called_with("exam:list", "exam:detail:exam-1")

        with patch("app.services.assessment.exam_workflow_service.run_exam_generation", AsyncMock(return_value={"exam_id": "exam-2"})), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as questions_invalidate:
            self.client.post("/exam/generate-questions-only", json={"file_ids": ["file-1"]})
        questions_invalidate.assert_called_with("exam:list", "exam:detail:exam-2")

        with patch("app.services.assessment.exam_workflow_service.generate_exam_pdf", AsyncMock(return_value="/tmp/exam-1.pdf")), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as pdf_invalidate:
            self.client.post(
                "/exam/exam-1/regenerate-pdf",
                json={"questions": [make_question_dict()], "exam_name": "Database Exam"},
            )
        pdf_invalidate.assert_called_with("exam:detail:exam-1")

        with patch("app.routers.exam.update_exam_record", return_value={"id": "exam-1"}), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as update_invalidate:
            self.client.put("/exam/exam-1", json={"title": "Updated"})
        update_invalidate.assert_called_with("exam:list", "exam:detail:exam-1")

        with patch("app.routers.exam.delete_exam_record", return_value={"message": "deleted"}), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as delete_invalidate:
            self.client.delete("/exam/exam-1")
        delete_invalidate.assert_called_with("exam:list", "exam:detail:exam-1")

        with patch("app.routers.exam.publish_exam_record", return_value={"id": "exam-1", "is_published": True}), patch(
            "app.routers.exam.redis_cache.invalidate_namespaces"
        ) as publish_invalidate:
            self.client.post("/exam/exam-1/publish", json={"is_published": True})
        publish_invalidate.assert_called_with("exam:list", "exam:detail:exam-1")

    def test_update_delete_and_publish_exam_routes(self):
        payload = {"title": "Updated", "questions": [make_question_dict()]}

        with patch("app.routers.exam.is_user_teacher", return_value=False):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 403)
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 403)
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 403)

        with patch("app.routers.exam.update_exam_record", return_value={"id": "exam-1"}):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 200)

        with patch("app.routers.exam.update_exam_record", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 404)

        with patch("app.routers.exam.delete_exam_record", return_value={"message": "deleted"}):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 200)

        with patch("app.routers.exam.delete_exam_record", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 404)

        with patch("app.routers.exam.publish_exam_record", return_value={"id": "exam-1", "is_published": True}):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 200)

    def test_start_and_submit_exam_routes(self):
        with patch("app.routers.exam.start_exam_submission", return_value={"submission_id": "sub-1", "started_at": "now", "attempt_no": 1, "duration_minutes": 30}):
            started = self.client.post("/exam/exam-1/start")
        self.assertEqual(started.status_code, 200)

        with patch("app.routers.exam.start_exam_submission", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 404)

        with patch("app.routers.exam.start_exam_submission", side_effect=NotReleasedError()):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 403)

        with patch("app.routers.exam.submit_exam_submission", return_value={"submission_id": "sub-1"}):
            submitted = self.client.post("/exam/submission/sub-1/submit", json={"answers": []})
        self.assertEqual(submitted.status_code, 200)

        with patch("app.routers.exam.submit_exam_submission", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 404)

        with patch("app.routers.exam.submit_exam_submission", side_effect=AlreadySubmittedError()):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 400)

    def test_submission_listing_and_manual_grading_routes(self):
        with patch("app.routers.exam.get_student_exam_submissions", return_value=[{"id": "sub-1"}]):
            mine = self.client.get("/exam/exam-1/my-submissions")
        self.assertEqual(mine.status_code, 200)

        with patch("app.routers.exam.get_student_exam_submissions", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/exam/exam-1/my-submissions").status_code, 500)

        with patch("app.routers.exam.is_user_teacher", return_value=False):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 403)
            self.assertEqual(self.client.put("/exam/submission/sub-1/grade", json={"answers_grades": []}).status_code, 403)

        with patch("app.routers.exam.get_exam_submission_rows", return_value=[{"id": "sub-1"}]):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 200)

        with patch("app.routers.exam.grade_exam_submission", return_value={"id": "sub-1"}):
            ok = self.client.put(
                "/exam/submission/sub-1/grade",
                json={"answers_grades": [{"answer_id": "answer-1", "marks_earned": 1}], "teacher_comment": "ok"},
            )
        self.assertEqual(ok.status_code, 200)

        with patch("app.routers.exam.grade_exam_submission", side_effect=NotFoundError("not found")):
            missing = self.client.put(
                "/exam/submission/sub-1/grade",
                json={"answers_grades": [{"answer_id": "answer-1", "marks_earned": 1}]},
            )
        self.assertEqual(missing.status_code, 404)

    def test_ai_grade_submission_routes(self):
        with patch("app.routers.exam.is_user_teacher", return_value=False):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 403)

        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value=None):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 404)

        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value={"answers": []}):
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
        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value=submission), patch(
            "app.services.assessment.exam_workflow_service.ai_grade_answer",
            AsyncMock(return_value={"marks_earned": 2, "feedback": "good", "is_correct": False}),
        ), patch(
            "app.services.assessment.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.assessment.exam_workflow_service.persist_ai_grade_exam_submission",
            return_value={"submission_id": "sub-1"},
        ):
            response = self.client.post("/exam/submission/sub-1/ai-grade")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["submission"]["submission_id"], "sub-1")

    def test_exam_additional_error_paths(self):
        payload = {"title": "Updated", "questions": [make_question_dict()]}

        with patch("app.routers.exam.update_exam_record", side_effect=Exception("boom")):
            self.assertEqual(self.client.put("/exam/exam-1", json=payload).status_code, 500)

        with patch("app.routers.exam.delete_exam_record", side_effect=Exception("boom")):
            self.assertEqual(self.client.delete("/exam/exam-1").status_code, 500)

        with patch("app.routers.exam.publish_exam_record", return_value={"id": "exam-1", "is_published": False}):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": False}).status_code, 200)

        with patch("app.routers.exam.publish_exam_record", side_effect=NotFoundError("not found")):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 404)

        with patch("app.routers.exam.publish_exam_record", side_effect=Exception("boom")):
            self.assertEqual(self.client.post("/exam/exam-1/publish", json={"is_published": True}).status_code, 500)

        with patch("app.routers.exam.start_exam_submission", side_effect=RuntimeError("boom")):
            self.assertEqual(self.client.post("/exam/exam-1/start").status_code, 500)

        with patch("app.routers.exam.submit_exam_submission", side_effect=RuntimeError("boom")):
            self.assertEqual(self.client.post("/exam/submission/sub-1/submit", json={"answers": []}).status_code, 500)

        with patch("app.routers.exam.get_exam_submission_rows", side_effect=Exception("boom")):
            self.assertEqual(self.client.get("/exam/exam-1/submissions").status_code, 500)

        with patch("app.routers.exam.get_student_exam_submissions", side_effect=Exception("boom")):
            self.assertEqual(self.client.get("/exam/exam-1/my-submissions").status_code, 500)

        with patch("app.routers.exam.grade_exam_submission", return_value={"id": "sub-1"}):
            result = asyncio.run(
                exam.grade_submission(
                    "sub-1",
                    exam.GradeSubmissionRequest(answers_grades=None, teacher_comment="ok"),
                    {"user_id": "teacher-1"},
                )
            )
        self.assertEqual(result["submission"]["id"], "sub-1")

        with patch("app.routers.exam.grade_exam_submission", side_effect=Exception("boom")):
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
        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value=mcq_only), patch(
            "app.services.assessment.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.assessment.exam_workflow_service.persist_ai_grade_exam_submission",
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
        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value=mixed_submission), patch(
            "app.services.assessment.exam_workflow_service.ai_grade_answer",
            AsyncMock(side_effect=RuntimeError("provider failed")),
        ), patch(
            "app.services.assessment.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(return_value="overall"),
        ), patch(
            "app.services.assessment.exam_workflow_service.persist_ai_grade_exam_submission",
            return_value={"submission_id": "sub-1"},
        ):
            response = self.client.post("/exam/submission/sub-1/ai-grade")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please grade manually", response.json()["graded_answers"][0]["teacher_feedback"])

        with patch("app.services.assessment.exam_workflow_service.get_submission_with_answers", return_value=mixed_submission), patch(
            "app.services.assessment.exam_workflow_service.ai_grade_answer",
            AsyncMock(return_value={"marks_earned": 1, "feedback": "ok", "is_correct": True}),
        ), patch(
            "app.services.assessment.exam_workflow_service.ai_generate_exam_overall_comment",
            AsyncMock(side_effect=RuntimeError("overall failed")),
        ):
            self.assertEqual(self.client.post("/exam/submission/sub-1/ai-grade").status_code, 500)


