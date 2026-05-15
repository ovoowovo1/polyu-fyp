from unittest import TestCase
from unittest.mock import patch

from app.services.core.exceptions import PermissionDeniedError
from app.services.pg import pg_access_control as access


class PgAccessControlTests(TestCase):
    def test_can_access_helpers_delegate_to_fetch_bool(self):
        cases = [
            (access.is_user_student, ("user-1",), True),
            (access.can_access_class, ("user-1", "class-1"), True),
            (access.can_access_document, ("user-1", "file-1"), True),
            (access.can_access_chunk, ("user-1", "chunk-1"), True),
            (access.can_access_exam, ("user-1", "exam-1"), True),
            (access.can_access_quiz, ("user-1", "quiz-1"), True),
        ]

        for func, args, expected in cases:
            with self.subTest(func=func.__name__), patch(
                "app.services.pg.pg_access_control.fetch_bool",
                return_value=expected,
            ) as fetch_bool:
                self.assertIs(func(*args), expected)
                fetch_bool.assert_called_once()

    def test_require_helpers_raise_when_fetch_bool_denies_access(self):
        cases = [
            (access.require_class_teacher, ("teacher-1", "class-1")),
            (access.require_document_teacher, ("teacher-1", "file-1")),
            (access.require_exam_teacher, ("teacher-1", "exam-1")),
            (access.require_submission_owner, ("student-1", "submission-1")),
            (access.require_submission_teacher, ("teacher-1", "submission-1")),
            (access.require_quiz_teacher, ("teacher-1", "quiz-1")),
        ]

        for func, args in cases:
            with self.subTest(func=func.__name__), patch(
                "app.services.pg.pg_access_control.fetch_bool",
                return_value=False,
            ):
                with self.assertRaises(PermissionDeniedError):
                    func(*args)

    def test_require_helpers_return_when_fetch_bool_allows_access(self):
        cases = [
            (access.require_class_teacher, ("teacher-1", "class-1")),
            (access.require_document_teacher, ("teacher-1", "file-1")),
            (access.require_exam_teacher, ("teacher-1", "exam-1")),
            (access.require_submission_owner, ("student-1", "submission-1")),
            (access.require_submission_teacher, ("teacher-1", "submission-1")),
            (access.require_quiz_teacher, ("teacher-1", "quiz-1")),
        ]

        for func, args in cases:
            with self.subTest(func=func.__name__), patch(
                "app.services.pg.pg_access_control.fetch_bool",
                return_value=True,
            ):
                self.assertIsNone(func(*args))

    def test_can_manage_documents_handles_empty_and_deduplicates_ids(self):
        with patch("app.services.pg.pg_access_control.fetch_bool") as fetch_bool:
            self.assertFalse(access.can_manage_documents("teacher-1", []))
            fetch_bool.assert_not_called()

        with patch("app.services.pg.pg_access_control.fetch_bool", return_value=True) as fetch_bool:
            self.assertTrue(access.can_manage_documents("teacher-1", ["file-1", "file-1", "file-2"]))
            params = fetch_bool.call_args.args[1]
            self.assertEqual(params, (["file-1", "file-1", "file-2"], "teacher-1", 2))
