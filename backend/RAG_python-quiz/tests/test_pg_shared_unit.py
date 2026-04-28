import unittest
from datetime import datetime
from unittest.mock import patch

from app.services import pg_shared
from tests.support import FakeCursor


class PgSharedTests(unittest.TestCase):
    def test_value_helpers_cover_json_time_and_stringify_paths(self):
        parsed = {"a": 1}
        self.assertIs(pg_shared.maybe_json_load(parsed), parsed)
        self.assertEqual(pg_shared.maybe_json_load("[1, 2]"), [1, 2])
        self.assertEqual(pg_shared.maybe_json_load(None, {}), {})
        self.assertEqual(pg_shared.maybe_json_load(3), 3)
        self.assertEqual(pg_shared.maybe_json_load("bad", [], swallow_errors=True), [])
        with self.assertRaises(ValueError):
            pg_shared.maybe_json_load("bad")

        ts = datetime(2025, 1, 2, 3, 4, 5)
        self.assertEqual(pg_shared.maybe_iso(ts), "2025-01-02T03:04:05")
        self.assertIsNone(pg_shared.maybe_iso(None))
        self.assertEqual(pg_shared.stringify_id("abc"), "abc")
        self.assertIsNone(pg_shared.stringify_id(None))
        self.assertEqual(pg_shared.stringify_id_list(["a", None, "b"]), ["a", "b"])

    def test_mapping_helpers_cover_document_and_exam_answer_shapes(self):
        self.assertEqual(
            pg_shared.map_document_row({"id": "doc-1", "name": "Lesson.pdf"}),
            {"id": "doc-1", "name": "Lesson.pdf"},
        )
        self.assertEqual(
            pg_shared.map_document_row(
                {"id": "doc-1", "name": "Lesson.pdf", "class_id": "class-1"},
                include_class_id=True,
            ),
            {"id": "doc-1", "name": "Lesson.pdf", "class_id": "class-1"},
        )
        self.assertEqual(
            pg_shared.filter_linked_documents(
                [{"id": "doc-1", "name": "Lesson.pdf"}, {"id": None, "name": "Ignored"}]
            ),
            [{"id": "doc-1", "name": "Lesson.pdf"}],
        )
        self.assertEqual(
            pg_shared.linked_document_ids(
                [{"id": "doc-1", "name": "Lesson.pdf"}, {"id": None, "name": "Ignored"}]
            ),
            ["doc-1"],
        )

        answer = pg_shared.map_exam_answer_row(
            {
                "id": "answer-1",
                "exam_question_id": "eq-1",
                "question_snapshot": '{"question_text":"What?"}',
                "answer_text": "A",
                "selected_options": "[1]",
                "time_spent_seconds": 10,
                "is_correct": True,
                "marks_earned": 5,
                "teacher_feedback": "Good",
                "attachments": '["file.png"]',
            },
            include_attachments=True,
        )
        self.assertEqual(answer["question_snapshot"]["question_text"], "What?")
        self.assertEqual(answer["selected_options"], [1])
        self.assertEqual(answer["attachments"], ["file.png"])

        answer = pg_shared.map_exam_answer_row(
            {
                "id": "answer-2",
                "exam_question_id": "eq-2",
                "question_snapshot": {"question_text": "Why?"},
                "answer_text": None,
                "selected_options": None,
                "time_spent_seconds": None,
                "is_correct": False,
                "marks_earned": 0,
                "teacher_feedback": None,
                "attachments": "bad-json",
            },
            include_attachments=True,
        )
        self.assertEqual(answer["question_snapshot"]["question_text"], "Why?")
        self.assertIsNone(answer["selected_options"])
        self.assertEqual(answer["attachments"], [])

        answer = pg_shared.map_exam_answer_row(
            {
                "id": "answer-3",
                "exam_question_id": "eq-3",
                "question_snapshot": None,
                "answer_text": "B",
                "selected_options": [2],
                "time_spent_seconds": 5,
                "is_correct": False,
                "marks_earned": 0,
                "teacher_feedback": "Retry",
            }
        )
        self.assertNotIn("attachments", answer)
        self.assertEqual(answer["selected_options"], [2])

    def test_database_helpers_cover_default_names_link_replacement_and_attempts(self):
        ts = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(fetchall_results=[[{"name": "a.pdf"}, {"name": "b.pdf"}]])
        names = pg_shared.fetch_default_document_names(cursor, ["file-1", "file-2"], limit=2)
        self.assertEqual(names, ["a.pdf", "b.pdf"])
        self.assertIn("LIMIT 2", cursor.executed[0][0])

        cursor = FakeCursor(
            fetchall_results=[
                [
                    {"owner_id": "quiz-1", "id": "doc-1", "name": "Lesson.pdf"},
                    {"owner_id": "quiz-1", "id": "doc-2", "name": "Slides.pdf"},
                ]
            ]
        )
        grouped_docs = pg_shared.fetch_linked_documents(
            cursor, "quiz_documents", "quiz_id", ["quiz-1"]
        )
        self.assertEqual(
            grouped_docs["quiz-1"],
            [
                {"id": "doc-1", "name": "Lesson.pdf"},
                {"id": "doc-2", "name": "Slides.pdf"},
            ],
        )
        self.assertEqual(
            pg_shared.fetch_linked_documents(cursor, "quiz_documents", "quiz_id", []),
            {},
        )

        cursor = FakeCursor()
        with patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            pg_shared.replace_linked_documents(cursor, "quiz_documents", "quiz_id", "quiz-1", [])
        self.assertEqual(cursor.executed[0], ("DELETE FROM quiz_documents WHERE quiz_id = %s", ("quiz-1",)))
        self.assertFalse(execute_values.called)

        cursor = FakeCursor()
        with patch("app.services.pg_shared.psycopg2.extras.execute_values") as execute_values:
            pg_shared.replace_linked_documents(
                cursor, "exam_documents", "exam_id", "exam-1", ["file-1", "file-2"]
            )
        self.assertTrue(execute_values.called)
        self.assertEqual(
            execute_values.call_args.args[2],
            [("exam-1", "file-1"), ("exam-1", "file-2")],
        )

        cursor = FakeCursor(fetchone_results=[{"max_attempt": 2}, None])
        self.assertEqual(
            pg_shared.next_attempt_no(
                cursor, "quiz_submissions", {"quiz_id": "quiz-1", "student_id": "student-1"}
            ),
            3,
        )
        self.assertIn("quiz_id = %s AND student_id = %s", cursor.executed[0][0])
        self.assertEqual(
            pg_shared.next_attempt_no(
                cursor, "exam_submissions", {"exam_id": "exam-1", "student_id": "student-1"}
            ),
            1,
        )

        cursor = FakeCursor(
            fetchone_results=[
                {"max_attempt": 1},
                {"id": "sub-1", "submitted_at": ts, "attempt_no": 2},
            ]
        )
        row, attempt_no = pg_shared.insert_submission_with_attempt(
            cursor,
            "quiz_submissions",
            {"quiz_id": "quiz-1", "student_id": "student-1"},
            "INSERT INTO quiz_submissions VALUES (%s, %s)",
            lambda value: ("quiz-1", value),
        )
        self.assertEqual(attempt_no, 2)
        self.assertEqual(row["id"], "sub-1")

    def test_submission_mappers_cover_quiz_and_exam_shapes(self):
        quiz_submission = pg_shared.map_quiz_submission_row(
            {
                "id": "sub-1",
                "student_id": "student-1",
                "full_name": "Student",
                "email": "student@example.com",
                "score": 2,
                "total_questions": 3,
                "answers_json": "not-json",
                "submitted_at": datetime(2025, 1, 2, 3, 4, 5),
                "attempt_no": 4,
            },
            include_student=True,
        )
        self.assertEqual(quiz_submission["answers"], [])
        self.assertEqual(quiz_submission["student_email"], "student@example.com")

        exam_submission = pg_shared.map_exam_submission_row(
            {
                "id": "sub-2",
                "exam_id": "exam-1",
                "student_id": "student-2",
                "student_name": "Learner",
                "student_email": "learner@example.com",
                "score": 5,
                "total_marks": 10,
                "time_spent_seconds": 60,
                "status": "submitted",
                "started_at": datetime(2025, 1, 2, 3, 4, 5),
                "submitted_at": datetime(2025, 1, 2, 4, 4, 5),
                "teacher_comment": "Good effort",
                "graded_at": datetime(2025, 1, 3, 3, 4, 5),
                "graded_by": "teacher-1",
                "grading_source": "teacher",
                "meta": '{"browser":"chrome"}',
            },
            answers=[{"id": "answer-1"}],
            include_student=True,
            include_graded_by=True,
            include_grading_source=True,
        )
        self.assertEqual(exam_submission["meta"]["browser"], "chrome")
        self.assertEqual(exam_submission["answers"][0]["id"], "answer-1")
        self.assertEqual(exam_submission["grading_source"], "teacher")
