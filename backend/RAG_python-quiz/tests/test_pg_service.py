import unittest
from datetime import datetime
from unittest.mock import patch

from app.services import pg_service
from tests.support import FakeConnection, FakeCursor


class FixedDateTime(datetime):
    @classmethod
    def now(cls):
        return cls(2025, 1, 2, 3, 4, 5)


class PgServiceBase(unittest.TestCase):
    def patch_conn(self, cursor: FakeCursor):
        return patch("app.services.pg_service._get_conn", return_value=FakeConnection(cursor))


class PgServiceVectorAndFileTests(PgServiceBase):
    def test_to_pgvector_formats_float_sequence(self):
        self.assertEqual(pg_service._to_pgvector([1, 2.5]), "[1.00000000,2.50000000]")

    def test_get_embedding_column_uses_settings_and_rejects_invalid_values(self):
        with patch(
            "app.services.pg_service.get_settings",
            return_value=type("Settings", (), {"openai_embedding_active_column": "embedding_v2"})(),
        ):
            self.assertEqual(pg_service._get_embedding_column(), "embedding_v2")

        with self.assertRaises(ValueError):
            pg_service._get_embedding_column("invalid")

    def test_setup_vector_index_is_noop(self):
        self.assertIsNone(pg_service.setup_vector_index())

    def test_find_document_by_hash_returns_document_or_none(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-1"}])
        with self.patch_conn(cursor):
            self.assertEqual(pg_service.find_document_by_hash("hash-1"), {"id": "doc-1"})

        cursor = FakeCursor(fetchone_results=[None])
        with self.patch_conn(cursor):
            self.assertIsNone(pg_service.find_document_by_hash("hash-2"))

    def test_create_graph_from_document_uses_requested_embedding_columns(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-1"}])
        document = {
            "hash": "hash-1",
            "name": "lesson.pdf",
            "size": 12,
            "mimetype": "application/pdf",
            "class_id": "class-1",
        }
        chunks = [
            {"text": "A", "metadata": {"pageNumber": 2}, "embedding": [0.1], "embedding_v2": [0.2]},
            {"text": "B", "embedding": [0.3], "embedding_v2": None},
        ]

        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
            result = pg_service.create_graph_from_document(document, chunks, embedding_column="embedding")

        self.assertEqual(result, {"fileId": "doc-1"})
        rows = execute_values.call_args.args[2]
        self.assertEqual(rows[0][0:5], ("doc-1", 2, 2, 0, "A"))
        self.assertEqual(rows[1][0:5], ("doc-1", 1, 1, 1, "B"))

    def test_create_graph_from_document_without_class_id_uses_default_embedding_column(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-2"}])
        document = {"hash": "hash-2", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf"}
        chunks = [{"text": "Only", "metadata": {}, "embedding": [0.4]}]

        with self.patch_conn(cursor), patch(
            "app.services.pg_service.get_settings",
            return_value=type("Settings", (), {"openai_embedding_active_column": "embedding"})(),
        ), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
            pg_service.create_graph_from_document(document, chunks)

        self.assertIn("INSERT INTO documents (hash, name, size_bytes, mimetype)", cursor.executed[0][0])
        self.assertEqual(execute_values.call_args.args[2][0][5], "[0.40000000]")

    def test_retrieve_graph_context_uses_default_and_v2_query_shapes(self):
        rows = [{"text": "chunk", "score": 0.4, "source": "doc", "page_start": 2, "fileid": "file-1", "chunkid": "chunk-1"}]
        cursor = FakeCursor(fetchall_results=[rows])
        with self.patch_conn(cursor), patch(
            "app.services.pg_service.get_settings",
            return_value=type("Settings", (), {"openai_embedding_active_column": "embedding"})(),
        ):
            result = pg_service.retrieve_graph_context([0.1], selected_file_ids=["file-1"])

        self.assertEqual(result[0]["fileId"], "file-1")
        self.assertNotIn("IS NOT NULL", cursor.executed[0][0])

        cursor = FakeCursor(fetchall_results=[rows])
        with self.patch_conn(cursor):
            pg_service.retrieve_graph_context([0.1], embedding_column="embedding_v2")
        self.assertIn("embedding_v2 IS NOT NULL", cursor.executed[0][0])

    def test_get_chunks_missing_embeddings_and_update_chunk_embeddings(self):
        cursor = FakeCursor(fetchall_results=[[{"id": "chunk-1", "text": "A"}]])
        with self.patch_conn(cursor):
            result = pg_service.get_chunks_missing_embeddings(limit=2)
        self.assertEqual(result, [{"id": "chunk-1", "text": "A"}])

        self.assertEqual(pg_service.update_chunk_embeddings([]), 0)

        cursor = FakeCursor()
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
            updated = pg_service.update_chunk_embeddings([{"id": "chunk-1", "embedding": [0.9]}])
        self.assertEqual(updated, 1)
        self.assertEqual(execute_values.call_args.args[2], [("chunk-1", "[0.90000000]")])

    def test_retrieve_context_helpers_cover_empty_and_keyword_paths(self):
        self.assertEqual(pg_service.retrieve_context_by_entities(["entity"]), [])

        cursor = FakeCursor(
            fetchall_results=[
                [{"text": "chunk", "score": None, "source": "lesson.pdf", "page_start": 1, "fileid": "file-1", "chunkid": "chunk-1"}],
                [{"text": "chunk", "score": 0.2, "source": "slides.pdf", "page_start": 2, "fileid": "file-2", "chunkid": "chunk-2"}],
            ]
        )
        with self.patch_conn(cursor):
            no_filter = pg_service.retrieve_context_by_keywords("sql")
            filtered = pg_service.retrieve_context_by_keywords("sql", selected_file_ids=["file-2"], k=5)

        self.assertIsNone(no_filter[0]["score"])
        self.assertEqual(no_filter[0]["source"], "lesson.pdf")
        self.assertEqual(filtered[0]["page"], 2)
        self.assertEqual(filtered[0]["source"], "slides.pdf")
        self.assertNotIn("ANY", cursor.executed[0][0])
        self.assertIn("ANY", cursor.executed[1][0])
        self.assertIn("JOIN public.documents AS d ON d.id = c.document_id", cursor.executed[0][0])
        self.assertNotIn("NULL::text AS source", cursor.executed[0][0])

    def test_file_listing_and_mutations_cover_success_and_missing_rows(self):
        upload_time = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(
            fetchall_results=[
                [{"id": "file-1", "name": "lesson.pdf", "size": 10, "mime_type": "application/pdf", "upload_date": upload_time, "total_chunks": 2}],
                [{"id": "file-2", "name": "slides.pdf", "size": 20, "mime_type": "application/pdf", "upload_date": upload_time, "total_chunks": 1}],
            ]
        )
        with self.patch_conn(cursor):
            all_files = pg_service.get_files_list()
            class_files = pg_service.get_files_list("class-1")

        self.assertEqual(all_files[0]["total_chunks"], 2)
        self.assertEqual(class_files[0]["filename"], "slides.pdf")

        cursor = FakeCursor(fetchone_results=[{"id": "file-1", "name": "lesson.pdf"}])
        with self.patch_conn(cursor):
            deleted = pg_service.delete_file("file-1")
        self.assertEqual(deleted["deletedFile"]["id"], "file-1")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.delete_file("missing")

        cursor = FakeCursor(fetchone_results=[{"id": "file-1", "name": "renamed.pdf"}])
        with self.patch_conn(cursor):
            renamed = pg_service.rename_file("file-1", "renamed.pdf")
        self.assertEqual(renamed["renamedFile"]["name"], "renamed.pdf")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.rename_file("missing", "name.pdf")

    def test_specific_file_and_source_detail_helpers_cover_missing_and_success(self):
        upload_time = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(
            fetchone_results=[{"id": "file-1", "name": "lesson.pdf", "size_bytes": 10, "mimetype": "application/pdf", "created_at": upload_time}],
            fetchall_results=[[{"id": "chunk-1", "content": "chunk text", "chunk_index": 0}]],
        )
        with self.patch_conn(cursor):
            result = pg_service.get_specific_file("file-1")
        self.assertEqual(result["chunks"][0]["chunk_index"], 0)

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_specific_file("missing")

        cursor = FakeCursor(fetchone_results=[{"file_id": "file-1", "page_start": 3, "chunk_index": 1, "source_file": "lesson.pdf", "chunk_id": "chunk-1"}])
        with self.patch_conn(cursor):
            detail = pg_service.get_source_details_by_chunk_id("chunk-1")
        self.assertEqual(detail["page_number"], 3)

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_source_details_by_chunk_id("missing")

    def test_get_files_text_content_validates_inputs_and_groups_content(self):
        with self.assertRaises(RuntimeError):
            pg_service.get_files_text_content([])

        with self.patch_conn(FakeCursor(fetchall_results=[[]])):
            with self.assertRaises(RuntimeError):
                pg_service.get_files_text_content(["file-1"])

        cursor = FakeCursor(
            fetchall_results=[
                [
                    {"file_name": "a.pdf", "text": "A1", "chunk_index": 0},
                    {"file_name": "a.pdf", "text": "A2", "chunk_index": 1},
                    {"file_name": "b.pdf", "text": "B1", "chunk_index": 0},
                ]
            ]
        )
        with self.patch_conn(cursor):
            content = pg_service.get_files_text_content(["file-1", "file-2"])
        self.assertIn("=== a.pdf ===", content)
        self.assertIn("B1", content)


class PgServiceQuizTests(PgServiceBase):
    def test_default_quiz_name_covers_single_multiple_and_empty_file_sets(self):
        with patch("app.services.pg_service.datetime", FixedDateTime):
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

        with patch("app.services.pg_service._get_conn", return_value=conn), patch(
            "app.services.pg_service.psycopg2.extras.execute_values"
        ) as execute_values:
            result = pg_service.save_quiz(quiz_data, ["file-1"], quiz_name="Quiz 1", class_id="class-1")

        self.assertEqual(result["name"], "Quiz 1")
        self.assertTrue(conn.committed)
        self.assertEqual(execute_values.call_args.args[2], [("quiz-1", "file-1")])

        cursor = FakeCursor(
            fetchone_results=[{"id": "quiz-2", "created_at": "raw"}],
            fetchall_results=[[{"name": "lesson.pdf"}]],
        )
        with self.patch_conn(cursor), patch("app.services.pg_service.datetime", FixedDateTime), patch(
            "app.services.pg_service.psycopg2.extras.execute_values"
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
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
            result = pg_service.update_quiz("quiz-1", {"questions": [{"q": 1}]}, name="Updated", file_ids=["file-1"])
        self.assertEqual(result["quiz_id"], "quiz-1")
        self.assertTrue(execute_values.called)

        cursor = FakeCursor(fetchone_results=[{"id": "quiz-2", "name": "Keep"}])
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
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


class PgServiceClassTests(PgServiceBase):
    def test_is_user_teacher_and_class_creation_cover_validation_and_success(self):
        with self.patch_conn(FakeCursor(fetchone_results=[{"role": "teacher"}])):
            self.assertTrue(pg_service.is_user_teacher("teacher-1"))

        with self.patch_conn(FakeCursor(fetchone_results=[{"role": "student"}])):
            self.assertFalse(pg_service.is_user_teacher("student-1"))

        with self.assertRaises(RuntimeError):
            pg_service.create_class_for_teacher("teacher-1", "")

        with patch("app.services.pg_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.create_class_for_teacher("teacher-1", "Class")

        row = {"id": "class-1", "teacher_id": "teacher-1", "name": "Databases", "code": "DB01", "created_at": datetime(2025, 1, 2, 3, 4, 5)}
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchone_results=[row])):
            created = pg_service.create_class_for_teacher("teacher-1", " Databases ", code="DB01")
        self.assertEqual(created["name"], "Databases")

    def test_class_listing_and_student_helpers_cover_success_and_error_paths(self):
        with patch("app.services.pg_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.list_classes_by_teacher("teacher-1")

        created_at = datetime(2025, 1, 2, 3, 4, 5)
        row = {
            "id": "class-1",
            "teacher_id": "teacher-1",
            "name": "Databases",
            "code": "DB01",
            "created_at": created_at,
            "student_count": 1,
            "students": [{"id": "student-1", "name": "Student", "email": "s@example.com"}],
        }
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchall_results=[[row]])):
            classes = pg_service.list_classes_by_teacher("teacher-1")
        self.assertEqual(classes[0]["student_count"], 1)

        cursor = FakeCursor(fetchone_results=[{"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"}, {"exists": 1}, {"exists": 1}], fetchall_results=[[row]])
        self.assertEqual(pg_service._get_user_by_email(cursor, "s@example.com")["email"], "s@example.com")
        self.assertTrue(pg_service._is_student_exists(cursor, "student-1"))
        self.assertTrue(pg_service._is_class_owned_by_teacher(cursor, "class-1", "teacher-1"))

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(PermissionError):
                pg_service.list_classes_for_student("student-1")

        list_row = {"id": "class-1", "teacher_id": "teacher-1", "name": "Databases", "code": None, "created_at": created_at, "student_count": 2}
        cursor = FakeCursor(fetchone_results=[{"exists": 1}], fetchall_results=[[list_row]])
        with self.patch_conn(cursor):
            classes = pg_service.list_classes_for_student("student-1")
        self.assertEqual(classes[0]["student_count"], 2)

    def test_invite_student_to_class_covers_validation_and_conflict_lookup(self):
        with patch("app.services.pg_service.is_user_teacher", return_value=False):
            with self.assertRaises(PermissionError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        with patch("app.services.pg_service.is_user_teacher", return_value=True):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "")

        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(PermissionError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, None])
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, {"id": "teacher-2", "email": "t@example.com", "full_name": "Teacher", "role": "teacher"}])
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "t@example.com")

        cursor = FakeCursor(fetchone_results=[{"ok": 1}, {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"}, None])
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            with self.assertRaises(RuntimeError):
                pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")

        cursor = FakeCursor(
            fetchone_results=[
                {"ok": 1},
                {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"},
                {"exists": 1},
                {"class_id": "class-1", "student_id": "student-1", "enrolled_at": datetime(2025, 1, 2, 3, 4, 5)},
            ]
        )
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            invited = pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")
        self.assertEqual(invited["student"]["email"], "s@example.com")

        cursor = FakeCursor(
            fetchone_results=[
                {"ok": 1},
                {"id": "student-1", "email": "s@example.com", "full_name": "Student", "role": "student"},
                {"exists": 1},
                None,
                {"class_id": "class-1", "student_id": "student-1", "enrolled_at": None},
            ]
        )
        with patch("app.services.pg_service.is_user_teacher", return_value=True), self.patch_conn(cursor):
            invited = pg_service.invite_student_to_class("teacher-1", "class-1", "s@example.com")
        self.assertEqual(invited["student_id"], "student-1")


class PgServiceExamTests(PgServiceBase):
    def test_default_exam_title_and_save_exam_cover_generated_and_manual_titles(self):
        with patch("app.services.pg_service.datetime", FixedDateTime):
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
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
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
        with self.patch_conn(cursor), patch("app.services.pg_service.datetime", FixedDateTime), patch(
            "app.services.pg_service.psycopg2.extras.execute_values"
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
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
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
        with self.patch_conn(cursor), patch("app.services.pg_service.psycopg2.extras.execute_values") as execute_values:
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
