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

    def test_refresh_token_migration_adds_revocable_token_storage(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "add_auth_refresh_tokens.sql"
        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens", sql)
        self.assertIn("token_hash text NOT NULL UNIQUE", sql)
        self.assertIn("revoked_at timestamptz", sql)
        self.assertIn("replaced_by_token_id uuid", sql)
        self.assertIn("ALTER TABLE public.auth_refresh_tokens ENABLE ROW LEVEL SECURITY;", sql)

        for function_name in [
            "auth_store_refresh_token",
            "auth_rotate_refresh_token",
            "auth_revoke_refresh_token",
        ]:
            self.assertIn(f"FUNCTION app_security.{function_name}", sql)

    def test_init_database_sql_covers_public_neon_setup_contract(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "000_init_database.sql"
        sql = migration_path.read_text(encoding="utf-8")

        for extension_name in ["pgcrypto", "vector", "pg_trgm", "pg_search"]:
            self.assertIn(f"CREATE EXTENSION IF NOT EXISTS {extension_name};", sql)

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
            "auth_refresh_tokens",
        ]:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table_name}", sql)
            self.assertIn(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY;", sql)

        for required_fragment in [
            "hash text UNIQUE",
            "embedding vector(3072)",
            "embedding_v2 vector(3072)",
            "entities_json jsonb",
            "tsv tsvector",
            "grading_source text DEFAULT NULL",
            "token_hash text NOT NULL UNIQUE",
            "revoked_at timestamptz",
            "replaced_by_token_id uuid",
            "USING bm25 (id, text)",
            "WITH (key_field='id')",
        ]:
            self.assertIn(required_fragment, sql)

        for function_name in [
            "request_user_id",
            "auth_lookup_user",
            "auth_mark_last_login",
            "auth_register_user",
            "auth_store_refresh_token",
            "auth_rotate_refresh_token",
            "auth_revoke_refresh_token",
            "can_access_document",
            "can_access_quiz",
            "can_access_exam",
        ]:
            self.assertIn(f"FUNCTION app_security.{function_name}", sql)

    def test_integration_workflow_runs_refresh_token_migration(self):
        workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "integration-tests.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        schema_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f tests/integration/schema.sql'
        rls_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/enable_rls_policies.sql'
        refresh_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/add_auth_refresh_tokens.sql'

        self.assertIn(schema_command, workflow)
        self.assertIn(rls_command, workflow)
        self.assertIn(refresh_command, workflow)
        self.assertLess(workflow.index(schema_command), workflow.index(rls_command))
        self.assertLess(workflow.index(rls_command), workflow.index(refresh_command))
