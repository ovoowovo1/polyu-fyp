from datetime import datetime
from unittest.mock import patch

from app.services import pg_service
from tests.pg_service_test_support import FixedDateTime, PgServiceBase
from tests.support import FakeConnection, FakeCursor


class PgQuizServiceTests(PgServiceBase):
    module_path = "app.services.pg_quiz_service"

    def test_default_quiz_name_covers_single_multiple_and_empty_file_sets(self):
        with patch("app.services.pg_quiz_service.datetime", FixedDateTime):
            cursor = FakeCursor(fetchall_results=[[{"name": "lesson.pdf"}]])
            self.assertIn("lesson -", pg_service._default_quiz_name(cursor, ["file-1"]))

            cursor = FakeCursor(fetchall_results=[[{"name": "a.pdf"}, {"name": "b.pdf"}]])
            self.assertIn("2", pg_service._default_quiz_name(cursor, ["file-1", "file-2"]))

            cursor = FakeCursor(fetchall_results=[[]])
            self.assertIn("(01/02 03:04)", pg_service._default_quiz_name(cursor, []))

    def test_save_quiz_covers_custom_and_generated_names(self):
        created_at = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(fetchone_results=[{"id": "quiz-1", "created_at": created_at}])
        conn = FakeConnection(cursor)
        quiz_data = {"questions": [{"q": 1}], "source_text_length": 10, "was_summarized": True}

        with patch("app.services.pg_quiz_service._get_conn", return_value=conn), patch(
            "app.services.pg_shared.psycopg2.extras.execute_values"
        ) as execute_values:
            result = pg_service.save_quiz(quiz_data, ["file-1"], quiz_name="Quiz 1", class_id="class-1")

        self.assertEqual(result["name"], "Quiz 1")
        self.assertTrue(conn.committed)
        self.assertEqual(execute_values.call_args.args[2], [("quiz-1", "file-1")])

        cursor = FakeCursor(
            fetchone_results=[{"id": "quiz-2", "created_at": "raw"}],
            fetchall_results=[[{"name": "lesson.pdf"}]],
        )
        with self.patch_conn(cursor), patch("app.services.pg_quiz_service.datetime", FixedDateTime), patch(
            "app.services.pg_shared.psycopg2.extras.execute_values"
        ):
            generated = pg_service.save_quiz({"questions": [{"q": 1}]}, ["file-1"])
        self.assertIn("lesson -", generated["name"])
        self.assertEqual(generated["created_at"], "raw")

    def test_update_quiz_covers_validation_missing_quiz_and_document_replacement(self):
        with self.assertRaises(RuntimeError):
            pg_service.update_quiz("quiz-1", {})

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.update_quiz("quiz-1", {"questions": []})

        cursor = FakeCursor(fetchone_results=[{"id": "quiz-1", "name": "Updated"}])
        with self.patch_conn(cursor), patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            result = pg_service.update_quiz("quiz-1", {"questions": [{"q": 1}]}, name="Updated", file_ids=["file-1"])
        self.assertEqual(result["quiz_id"], "quiz-1")
        self.assertTrue(execute_values.called)

        cursor = FakeCursor(fetchone_results=[{"id": "quiz-2", "name": "Keep"}])
        with self.patch_conn(cursor), patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            pg_service.update_quiz("quiz-2", {"questions": []}, file_ids=[])
        self.assertFalse(execute_values.called)

    def test_get_all_quizzes_covers_anonymous_teacher_and_student_views(self):
        created_at = datetime(2025, 1, 2, 3, 4, 5)
        rows = [{"id": "quiz-1", "name": None, "num_questions": 2, "created_at": created_at, "was_summarized": False, "source_text_length": 12, "file_ids": ["file-1"]}]
        docs = [{"quiz_id": "quiz-1", "id": "file-1", "name": "lesson.pdf"}, {"quiz_id": "quiz-1", "id": None, "name": "ignored"}]

        cursor = FakeCursor(fetchall_results=[rows, docs])
        with self.patch_conn(cursor):
            quizzes = pg_service.get_all_quizzes()
        self.assertEqual(quizzes[0]["documents"][0]["name"], "lesson.pdf")
        self.assertEqual(quizzes[0]["name"], "未命名測驗")

        cursor = FakeCursor(fetchone_results=[{"role": "teacher"}], fetchall_results=[rows, docs])
        with self.patch_conn(cursor):
            quizzes = pg_service.get_all_quizzes("teacher-1")
        self.assertEqual(quizzes[0]["file_ids"], ["file-1"])

        cursor = FakeCursor(fetchone_results=[{"role": "student"}], fetchall_results=[rows, docs])
        with self.patch_conn(cursor):
            quizzes = pg_service.get_all_quizzes("student-1")
        self.assertEqual(quizzes[0]["id"], "quiz-1")

    def test_get_quizzes_by_class_and_delete_quiz_cover_success_and_missing(self):
        created_at = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(
            fetchall_results=[
                [{"id": "quiz-1", "name": None, "num_questions": 2, "created_at": created_at, "was_summarized": True, "source_text_length": 30, "file_ids": ["file-1"]}],
                [{"quiz_id": "quiz-1", "id": "file-1", "name": "lesson.pdf"}],
            ]
        )
        with self.patch_conn(cursor):
            quizzes = pg_service.get_quizzes_by_class("class-1")
        self.assertEqual(quizzes[0]["documents"][0]["id"], "file-1")

        cursor = FakeCursor(fetchone_results=[{"id": "quiz-1"}])
        with self.patch_conn(cursor):
            deleted = pg_service.delete_quiz("quiz-1")
        self.assertEqual(deleted["quiz_id"], "quiz-1")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.delete_quiz("missing")

    def test_get_quiz_by_id_enforces_access_and_parses_question_payloads(self):
        created_at = datetime(2025, 1, 2, 3, 4, 5)
        quiz_row = {
            "id": "quiz-1",
            "name": None,
            "questions_json": '[{"question":"What?"}]',
            "num_questions": 1,
            "created_at": created_at,
            "was_summarized": False,
            "source_text_length": 10,
        }
        docs_rows = [{"id": "file-1", "name": "lesson.pdf", "class_id": "class-1"}]

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_quiz_by_id("missing")

        cursor = FakeCursor(fetchone_results=[quiz_row, {"role": "teacher"}, {"ok": 1}], fetchall_results=[docs_rows])
        with self.patch_conn(cursor):
            teacher_view = pg_service.get_quiz_by_id("quiz-1", user_id="teacher-1")
        self.assertEqual(teacher_view["questions"][0]["question"], "What?")

        cursor = FakeCursor(fetchone_results=[quiz_row, {"role": "student"}, {"ok": 1}], fetchall_results=[docs_rows])
        with self.patch_conn(cursor):
            student_view = pg_service.get_quiz_by_id("quiz-1", user_id="student-1")
        self.assertEqual(student_view["documents"][0]["name"], "lesson.pdf")

        cursor = FakeCursor(fetchone_results=[quiz_row, {"role": "teacher"}, None], fetchall_results=[docs_rows])
        with self.patch_conn(cursor):
            with self.assertRaises(PermissionError):
                pg_service.get_quiz_by_id("quiz-1", user_id="teacher-2")

    def test_quiz_submission_helpers_cover_none_string_and_invalid_json(self):
        submitted_at = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(fetchone_results=[{"id": "quiz-1"}, {"max_attempt": 2}, {"id": "sub-1", "submitted_at": submitted_at, "attempt_no": 3}])
        with self.patch_conn(cursor):
            result = pg_service.submit_quiz_result("quiz-1", "student-1", [{"answer": "A"}], 1, 2)
        self.assertEqual(result["attempt_no"], 3)

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.submit_quiz_result("quiz-1", "student-1", [], 0, 0)

        rows = [
            {"id": "sub-1", "student_id": "student-1", "score": 1, "total_questions": 2, "submitted_at": submitted_at, "answers_json": None, "attempt_no": 1, "full_name": "Student", "email": "s@example.com"},
            {"id": "sub-2", "student_id": "student-2", "score": 2, "total_questions": 2, "submitted_at": submitted_at, "answers_json": '[{\"answer\":\"B\"}]', "attempt_no": 2, "full_name": "Other", "email": "o@example.com"},
            {"id": "sub-3", "student_id": "student-3", "score": 0, "total_questions": 2, "submitted_at": submitted_at, "answers_json": "not-json", "attempt_no": 3, "full_name": "Third", "email": "t@example.com"},
        ]
        with self.patch_conn(FakeCursor(fetchall_results=[rows])):
            submissions = pg_service.get_quiz_submissions("quiz-1")
        self.assertEqual(submissions[0]["answers"], [])
        self.assertEqual(submissions[1]["answers"][0]["answer"], "B")
        self.assertEqual(submissions[2]["answers"], [])

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            self.assertIsNone(pg_service.get_student_quiz_submission("quiz-1", "student-1"))

        cursor = FakeCursor(fetchone_results=[{"id": "sub-1", "score": 1, "total_questions": 2, "answers_json": '[{\"answer\":\"A\"}]', "submitted_at": submitted_at}])
        with self.patch_conn(cursor):
            submission = pg_service.get_student_quiz_submission("quiz-1", "student-1")
        self.assertEqual(submission["answers"][0]["answer"], "A")
