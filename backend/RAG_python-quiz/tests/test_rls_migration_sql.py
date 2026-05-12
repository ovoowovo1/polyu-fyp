from pathlib import Path
import unittest


class RlsMigrationSqlTests(unittest.TestCase):
    def test_enable_rls_migration_covers_user_facing_tables_and_auth_helpers(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "enable_rls_policies.sql"
        sql = migration_path.read_text(encoding="utf-8")

        for table_name in [
            "users",
            "teachers",
            "students",
            "classes",
            "class_students",
            "documents",
            "chunks",
            "quizzes",
            "quiz_documents",
            "quiz_submissions",
            "exams",
            "exam_questions",
            "exam_documents",
            "exam_submissions",
            "exam_answers",
        ]:
            self.assertIn(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY;", sql)
            self.assertIn(f" ON public.{table_name}", sql)

        for function_name in [
            "request_user_id",
            "auth_lookup_user",
            "auth_mark_last_login",
            "auth_register_user",
            "lookup_student_for_invite",
            "is_class_owned_by_teacher",
            "can_access_document",
            "can_access_quiz",
            "can_access_exam",
        ]:
            self.assertIn(f"FUNCTION app_security.{function_name}", sql)
