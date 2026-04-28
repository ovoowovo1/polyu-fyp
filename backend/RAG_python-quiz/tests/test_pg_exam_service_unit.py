from datetime import datetime
from unittest.mock import patch

from app.services import pg_service
from tests.pg_service_test_support import FixedDateTime, PgServiceBase
from tests.support import FakeCursor


class PgExamServiceTests(PgServiceBase):
    module_path = "app.services.pg_exam_service"

    def test_default_exam_title_and_save_exam_cover_generated_and_manual_titles(self):
        with patch("app.services.pg_exam_service.datetime", FixedDateTime):
            cursor = FakeCursor(fetchall_results=[[{"name": "lesson.pdf"}]])
            self.assertIn("lesson -", pg_service._default_exam_title(cursor, ["file-1"]))

            cursor = FakeCursor(fetchall_results=[[{"name": "a.pdf"}, {"name": "b.pdf"}]])
            self.assertIn("2", pg_service._default_exam_title(cursor, ["a", "b"]))

            cursor = FakeCursor(fetchall_results=[[]])
            self.assertIn("(01/02 03:04)", pg_service._default_exam_title(cursor, []))

        created_at = datetime(2025, 1, 2, 3, 4, 5)
        row = {"id": "exam-1", "created_at": created_at}
        questions = [
            {"question_id": "q-1", "question_type": "multiple_choice", "correct_answer_index": 1, "marks": 2},
            {"question_id": "q-2", "question_type": "short_answer", "marks": 3},
        ]
        cursor = FakeCursor(fetchone_results=[row])
        with self.patch_conn(cursor), patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            result = pg_service.save_exam(
                "exam-1",
                "Database Exam",
                questions,
                ["file-1"],
                class_id="class-1",
                owner_id="teacher-1",
                difficulty="hard",
                duration_minutes=60,
                pdf_path="/tmp/exam.pdf",
                description="Midterm",
            )
        self.assertEqual(result["total_marks"], 5)
        self.assertTrue(execute_values.called)

        cursor = FakeCursor(fetchone_results=[row], fetchall_results=[[{"name": "lesson.pdf"}]])
        with self.patch_conn(cursor), patch("app.services.pg_exam_service.datetime", FixedDateTime), patch(
            "app.services.pg_shared.psycopg2.extras.execute_values"
        ) as execute_values:
            generated = pg_service.save_exam("exam-2", "", questions[:1], [])
        self.assertIn("lesson -", generated["title"])
        self.assertFalse(execute_values.called)

    def test_get_exams_by_class_and_get_exam_by_id_cover_visibility_and_question_paths(self):
        created_at = datetime(2025, 1, 2, 3, 4, 5)
        updated_at = datetime(2025, 1, 3, 3, 4, 5)
        row = {
            "id": "exam-1",
            "title": None,
            "description": "Midterm",
            "difficulty": "medium",
            "total_marks": 5,
            "duration_minutes": 60,
            "created_at": created_at,
            "updated_at": updated_at,
            "is_published": True,
            "pdf_path": "/tmp/exam.pdf",
            "owner_id": "teacher-1",
            "start_at": None,
            "end_at": None,
            "num_questions": 2,
            "file_ids": ["file-1"],
        }
        cursor = FakeCursor(fetchall_results=[[row], [{"exam_id": "exam-1", "id": "file-1", "name": "lesson.pdf"}]])
        with self.patch_conn(cursor):
            exams = pg_service.get_exams_by_class("class-1")
        self.assertEqual(exams[0]["documents"][0]["name"], "lesson.pdf")
        self.assertEqual(exams[0]["title"], "未命名考試")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_exam_by_id("missing")

        exam_row = {
            "id": "exam-1",
            "title": None,
            "description": "Midterm",
            "questions_json": [],
            "difficulty": "medium",
            "total_marks": 5,
            "duration_minutes": 60,
            "class_id": "class-1",
            "owner_id": "teacher-1",
            "created_at": created_at,
            "updated_at": updated_at,
            "is_published": True,
            "pdf_path": "/tmp/exam.pdf",
            "start_at": None,
            "end_at": None,
        }
        docs_rows = [{"id": "file-1", "name": "lesson.pdf", "class_id": "class-1"}]
        eq_rows = [{"id": "eq-1", "position": 0, "question_snapshot": '{"question_type":"multiple_choice","question_text":"What?","correct_answer_index":1,"model_answer":"A","marking_scheme":[],"rationale":"Because","question_id":"q-1"}', "max_marks": 2}]
        cursor = FakeCursor(fetchone_results=[exam_row, {"role": "student"}, {"ok": 1}], fetchall_results=[docs_rows, eq_rows])
        with self.patch_conn(cursor):
            student_exam = pg_service.get_exam_by_id("exam-1", user_id="student-1", include_answers=False)
        self.assertNotIn("correct_answer_index", student_exam["questions"][0])
        self.assertEqual(student_exam["documents"][0]["id"], "file-1")

        unpublished_row = dict(exam_row)
        unpublished_row["is_published"] = False
        cursor = FakeCursor(fetchone_results=[unpublished_row, {"role": "student"}], fetchall_results=[docs_rows, eq_rows])
        with self.patch_conn(cursor):
            with self.assertRaises(PermissionError):
                pg_service.get_exam_by_id("exam-1", user_id="student-1")

        cursor = FakeCursor(fetchone_results=[exam_row, {"role": "student"}, None], fetchall_results=[docs_rows, eq_rows])
        with self.patch_conn(cursor):
            with self.assertRaises(PermissionError):
                pg_service.get_exam_by_id("exam-1", user_id="student-1")

        fallback_row = dict(exam_row)
        fallback_row["questions_json"] = '[{"question_text":"Fallback","correct_answer_index":2}]'
        cursor = FakeCursor(fetchone_results=[fallback_row], fetchall_results=[docs_rows, []])
        with self.patch_conn(cursor):
            fallback_exam = pg_service.get_exam_by_id("exam-1")
        self.assertEqual(fallback_exam["questions"][0]["question_text"], "Fallback")

    def test_update_delete_publish_and_start_exam_cover_success_and_failure(self):
        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.update_exam("missing")

        existing = {"id": "exam-1", "questions_json": "[]"}
        cursor = FakeCursor(fetchone_results=[existing, {"id": "exam-1", "title": "Updated", "total_marks": 3}])
        with self.patch_conn(cursor), patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            updated = pg_service.update_exam(
                "exam-1",
                title="Updated",
                description="Desc",
                questions=[{"question_text": "Q1", "marks": 3}],
                difficulty="hard",
                duration_minutes=45,
                file_ids=["file-1"],
                start_at="2025-01-01T00:00:00",
                end_at="2025-01-02T00:00:00",
            )
        self.assertEqual(updated["total_marks"], 3)
        self.assertTrue(execute_values.called)

        cursor = FakeCursor(fetchone_results=[existing, {"id": "exam-1", "title": "Updated", "total_marks": 0}])
        with self.patch_conn(cursor), patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            pg_service.update_exam("exam-1", duration_minutes=0, file_ids=[], start_at="", end_at="")
        self.assertFalse(execute_values.called)

        cursor = FakeCursor(fetchone_results=[{"id": "exam-1", "title": "Exam"}])
        with self.patch_conn(cursor):
            deleted = pg_service.delete_exam("exam-1")
        self.assertEqual(deleted["exam_id"], "exam-1")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.delete_exam("missing")

        cursor = FakeCursor(fetchone_results=[{"id": "exam-1", "title": "Exam", "is_published": True}])
        with self.patch_conn(cursor):
            published = pg_service.publish_exam("exam-1")
        self.assertTrue(published["is_published"])

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.publish_exam("missing")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.start_exam_submission("exam-1", "student-1")

        cursor = FakeCursor(fetchone_results=[{"id": "exam-1", "is_published": False, "duration_minutes": 30, "start_at": None, "end_at": None}])
        with self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.start_exam_submission("exam-1", "student-1")

        cursor = FakeCursor(fetchone_results=[{"id": "exam-1", "is_published": True, "duration_minutes": 30, "start_at": None, "end_at": None}, {"max_attempt": 1}, {"id": "sub-1", "started_at": datetime(2025, 1, 2, 3, 4, 5), "attempt_no": 2}])
        with self.patch_conn(cursor):
            started = pg_service.start_exam_submission("exam-1", "student-1", meta={"source": "web"})
        self.assertEqual(started["attempt_no"], 2)

    def test_submit_exam_and_submission_queries_cover_multiple_paths(self):
        submission_row = {"id": "sub-1", "exam_id": "exam-1", "status": "in_progress", "questions_json": [], "total_marks": 5}
        eq_rows = [
            {"id": "eq-1", "position": 0, "question_snapshot": '{"question_id":"q-1","question_type":"multiple_choice","correct_answer_index":1}', "max_marks": 2},
            {"id": "eq-2", "position": 1, "question_snapshot": {"question_id": "q-2", "question_type": "short_answer"}, "max_marks": 3},
        ]
        submit_row = {"id": "sub-1", "submitted_at": datetime(2025, 1, 2, 3, 4, 5), "score": 2, "total_marks": 5}
        cursor = FakeCursor(fetchone_results=[submission_row, submit_row], fetchall_results=[eq_rows])
        answers = [
            {"exam_question_id": "eq-1", "answer_index": 1, "time_spent_seconds": 10},
            {"question_id": "q-2", "answer_text": "Explain"},
            {"question_id": "unknown", "answer_text": "Ignored"},
        ]
        with self.patch_conn(cursor):
            result = pg_service.submit_exam("sub-1", answers, time_spent_seconds=20)
        self.assertEqual(result["score"], 2)

        cursor = FakeCursor(fetchone_results=[submission_row, submit_row], fetchall_results=[eq_rows])
        with self.patch_conn(cursor):
            result = pg_service.submit_exam("sub-1", [{"exam_question_id": "eq-1", "selected_options": [1]}])
        self.assertEqual(result["status"], "submitted")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.submit_exam("missing", [])

        with self.patch_conn(FakeCursor(fetchone_results=[{"id": "sub-1", "exam_id": "exam-1", "status": "submitted", "questions_json": [], "total_marks": 1}])):
            with self.assertRaises(RuntimeError):
                pg_service.submit_exam("sub-1", [])

        submitted_at = datetime(2025, 1, 2, 3, 4, 5)
        graded_at = datetime(2025, 1, 3, 3, 4, 5)
        rows = [
            {
                "id": "sub-1",
                "student_id": "student-1",
                "attempt_no": 1,
                "score": 5,
                "total_marks": 5,
                "time_spent_seconds": 60,
                "status": "submitted",
                "started_at": submitted_at,
                "submitted_at": submitted_at,
                "teacher_comment": "Good",
                "graded_by": "teacher-1",
                "graded_at": graded_at,
                "meta": '{"browser":"chrome"}',
                "student_name": "Student",
                "student_email": "s@example.com",
            }
        ]
        answer_rows = [
            {
                "submission_id": "sub-1",
                "id": "answer-1",
                "exam_question_id": "eq-1",
                "question_snapshot": '{"question_text":"What?"}',
                "answer_text": "A",
                "selected_options": "[1]",
                "time_spent_seconds": 10,
                "is_correct": True,
                "marks_earned": 5,
                "teacher_feedback": "Well done",
                "attachments": '["file.png"]',
            }
        ]
        cursor = FakeCursor(fetchall_results=[rows, answer_rows])
        with self.patch_conn(cursor):
            submissions = pg_service.get_exam_submissions("exam-1")
        self.assertEqual(submissions[0]["answers"][0]["attachments"][0], "file.png")
        self.assertEqual(submissions[0]["meta"]["browser"], "chrome")

        cursor = FakeCursor(fetchall_results=[[]])
        with self.patch_conn(cursor):
            self.assertEqual(pg_service.get_exam_submissions("exam-1"), [])

        student_rows = [
            {
                "id": "sub-1",
                "attempt_no": 1,
                "score": 3,
                "total_marks": 5,
                "time_spent_seconds": 60,
                "status": "graded",
                "started_at": submitted_at,
                "submitted_at": submitted_at,
                "teacher_comment": "ok",
                "graded_at": graded_at,
                "meta": '{"source":"mobile"}',
            }
        ]
        student_answers = [
            {
                "submission_id": "sub-1",
                "id": "answer-1",
                "exam_question_id": "eq-1",
                "question_snapshot": {"question_text": "What?"},
                "answer_text": "A",
                "selected_options": [1],
                "time_spent_seconds": 10,
                "is_correct": True,
                "marks_earned": 3,
                "teacher_feedback": "fine",
            }
        ]
        cursor = FakeCursor(fetchall_results=[student_rows, student_answers])
        with self.patch_conn(cursor):
            mine = pg_service.get_student_exam_submissions("exam-1", "student-1")
        self.assertEqual(mine[0]["answers"][0]["selected_options"], [1])
        self.assertEqual(mine[0]["meta"]["source"], "mobile")

        cursor = FakeCursor(fetchall_results=[[]])
        with self.patch_conn(cursor):
            self.assertEqual(pg_service.get_student_exam_submissions("exam-1", "student-1"), [])

    def test_manual_and_ai_grading_helpers_cover_all_update_modes(self):
        graded_at = datetime(2025, 1, 2, 3, 4, 5)
        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.grade_exam_submission("sub-1", "teacher-1")

        cursor = FakeCursor(fetchone_results=[{"id": "sub-1", "total_marks": 5}, {"total_score": 4}, {"id": "sub-1", "score": 4, "graded_at": graded_at}])
        with self.patch_conn(cursor):
            graded = pg_service.grade_exam_submission(
                "sub-1",
                "teacher-1",
                answers_grades=[
                    {"answer_id": "answer-1", "marks_earned": 2, "teacher_feedback": "ok"},
                    {"exam_question_id": "eq-2", "marks_earned": 2, "teacher_feedback": "good"},
                ],
                teacher_comment="Overall good",
            )
        self.assertEqual(graded["score"], 4)

        cursor = FakeCursor(fetchone_results=[{"id": "sub-1", "total_marks": 5}, {"total_score": 0}, {"id": "sub-1", "score": 0, "graded_at": graded_at}])
        with self.patch_conn(cursor):
            pg_service.grade_exam_submission("sub-1", "teacher-1")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            self.assertIsNone(pg_service.get_submission_with_answers("missing"))

        sub_row = {
            "id": "sub-1",
            "exam_id": "exam-1",
            "student_id": "student-1",
            "score": 4,
            "total_marks": 5,
            "status": "graded",
            "started_at": graded_at,
            "submitted_at": graded_at,
            "teacher_comment": "Good",
            "graded_at": graded_at,
            "graded_by": "teacher-1",
            "grading_source": "teacher",
            "meta": {"x": 1},
        }
        answers = [
            {
                "id": "answer-1",
                "exam_question_id": "eq-1",
                "question_snapshot": '{"question_text":"What?"}',
                "answer_text": "A",
                "selected_options": "[1]",
                "time_spent_seconds": 10,
                "is_correct": True,
                "marks_earned": 4,
                "teacher_feedback": "Great",
            }
        ]
        cursor = FakeCursor(fetchone_results=[sub_row], fetchall_results=[answers])
        with self.patch_conn(cursor):
            submission = pg_service.get_submission_with_answers("sub-1")
        self.assertEqual(submission["answers"][0]["question_snapshot"]["question_text"], "What?")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.ai_grade_exam_submission("missing", [])

        cursor = FakeCursor(fetchone_results=[{"id": "sub-1", "total_marks": 5}, {"total_score": 3}, {"id": "sub-1", "score": 3, "graded_at": graded_at, "status": "ai_graded", "teacher_comment": "AI comment"}])
        with self.patch_conn(cursor):
            ai_result = pg_service.ai_grade_exam_submission(
                "sub-1",
                [
                    {"answer_id": "answer-1", "marks_earned": 1, "teacher_feedback": "A", "is_correct": False},
                    {"exam_question_id": "eq-2", "marks_earned": 2, "teacher_feedback": "B", "is_correct": True},
                ],
                teacher_comment="AI comment",
            )
        self.assertEqual(ai_result["teacher_comment"], "AI comment")

        cursor = FakeCursor(fetchone_results=[{"id": "sub-1", "total_marks": 5}, {"total_score": 2}, {"id": "sub-1", "score": 2, "graded_at": graded_at, "status": "ai_graded", "teacher_comment": None}])
        with self.patch_conn(cursor):
            ai_result = pg_service.ai_grade_exam_submission("sub-1", [{"exam_question_id": "eq-1", "marks_earned": 2, "teacher_feedback": None, "is_correct": True}])
        self.assertEqual(ai_result["status"], "ai_graded")
