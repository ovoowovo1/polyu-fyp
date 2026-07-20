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
            "chunk_media",
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
            "can_access_chunk_media",
            "can_manage_chunk_media",
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
            "chunk_media",
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
            "hash text",
            "idx_documents_class_hash ON public.documents(class_id, hash)",
            "embedding vector(3072)",
            "embedding_v2 vector(3072)",
            "entities_json jsonb",
            "tsv tsvector",
            "grading_source text DEFAULT NULL",
            "token_hash text NOT NULL UNIQUE",
            "revoked_at timestamptz",
            "replaced_by_token_id uuid",
            "CREATE TABLE IF NOT EXISTS public.chunk_media",
            "USING bm25 (id, text)",
            "WITH (key_field='id')",
        ]:
            self.assertIn(required_fragment, sql)

        self.assertIn(
            """CREATE POLICY documents_select_allowed ON public.documents
FOR SELECT USING (
    app_security.can_access_document(id)
    OR app_security.can_manage_document_class(class_id)
);""",
            sql,
        )

        for policy_fragment in [
            "CREATE POLICY chunk_media_select_allowed ON public.chunk_media",
            "CREATE POLICY chunk_media_insert_teacher ON public.chunk_media",
            "CREATE POLICY chunk_media_delete_teacher ON public.chunk_media",
        ]:
            self.assertIn(policy_fragment, sql)

        for function_name in [
            "request_user_id",
            "auth_lookup_user",
            "auth_mark_last_login",
            "auth_register_user",
            "auth_store_refresh_token",
            "auth_rotate_refresh_token",
            "auth_revoke_refresh_token",
            "can_access_document",
            "can_access_chunk_media",
            "can_manage_chunk_media",
            "can_access_quiz",
            "can_access_exam",
        ]:
            self.assertIn(f"FUNCTION app_security.{function_name}", sql)

    def test_enable_rls_migration_allows_document_insert_returning_for_class_manager(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "enable_rls_policies.sql"
        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn(
            """CREATE POLICY documents_select_allowed ON public.documents
FOR SELECT USING (
    app_security.can_access_document(id)
    OR app_security.can_manage_document_class(class_id)
);""",
            sql,
        )

    def test_chunk_media_migration_creates_cascade_media_storage(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "add_chunk_media.sql"
        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS public.chunk_media", sql)
        self.assertIn("chunk_id uuid PRIMARY KEY REFERENCES public.chunks(id) ON DELETE CASCADE", sql)
        self.assertIn("mimetype text NOT NULL", sql)
        self.assertIn("data bytea NOT NULL", sql)

    def test_integration_workflow_runs_refresh_token_migration(self):
        workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "integration-tests.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        schema_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f tests/integration/schema.sql'
        document_hash_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/scope_document_hash_by_class.sql'
        chunk_media_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/add_chunk_media.sql'
        rls_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/enable_rls_policies.sql'
        media_smoke_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f tests/integration/rls_chunk_media.sql'
        refresh_command = 'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f migrations/add_auth_refresh_tokens.sql'

        self.assertIn(schema_command, workflow)
        self.assertIn(document_hash_command, workflow)
        self.assertIn(chunk_media_command, workflow)
        self.assertIn(rls_command, workflow)
        self.assertIn(media_smoke_command, workflow)
        self.assertIn(refresh_command, workflow)
        self.assertLess(workflow.index(schema_command), workflow.index(rls_command))
        self.assertLess(workflow.index(schema_command), workflow.index(document_hash_command))
        self.assertLess(workflow.index(document_hash_command), workflow.index(rls_command))
        self.assertLess(workflow.index(chunk_media_command), workflow.index(rls_command))
        self.assertLess(workflow.index(rls_command), workflow.index(media_smoke_command))
        self.assertLess(workflow.index(media_smoke_command), workflow.index(refresh_command))
        self.assertLess(workflow.index(rls_command), workflow.index(refresh_command))

    def test_document_hash_migration_scopes_uniqueness_to_class(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "scope_document_hash_by_class.sql"
        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn("DROP CONSTRAINT IF EXISTS documents_hash_key", sql)
        self.assertIn("DROP INDEX IF EXISTS public.idx_documents_hash", sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_class_hash ON public.documents(class_id, hash)", sql)
