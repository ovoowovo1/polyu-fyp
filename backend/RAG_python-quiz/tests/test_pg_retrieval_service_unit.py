import asyncio
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from app.services.pg import pg_retrieval_service as pg_service
from app.services.pg import pg_retrieval_documents
from app.services.pg import pg_retrieval_keywords
from app.services.pg import pg_shared
from tests.pg_service_test_support import PgServiceBase
from tests.support import FakeConnection, FakeCursor, make_settings


class PgRetrievalServiceTests(PgServiceBase):
    module_path = "app.services.pg.pg_retrieval_service"

    def test_to_pgvector_formats_float_sequence(self):
        self.assertEqual(pg_shared._to_pgvector([1, 2.5]), "[1.00000000,2.50000000]")


    def test_safe_postgres_diagnostics_excludes_connection_and_query_data(self):
        plain_error = RuntimeError("database error")
        self.assertEqual(
            pg_retrieval_documents._safe_postgres_diagnostics(plain_error),
            {"sqlstate": None, "schema": None, "table": None, "constraint": None, "message": None},
        )

        postgres_error = RuntimeError("database error")
        postgres_error.pgcode = "42501"
        postgres_error.diag = SimpleNamespace(
            schema_name="public",
            table_name="documents",
            constraint_name="documents_class_hash_key",
            message_primary="new row violates row-level security policy",
        )
        self.assertEqual(
            pg_retrieval_documents._safe_postgres_diagnostics(postgres_error),
            {
                "sqlstate": "42501",
                "schema": "public",
                "table": "documents",
                "constraint": "documents_class_hash_key",
                "message": "new row violates row-level security policy",
            },
        )

    def test_find_document_by_hash_returns_document_or_none(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-1"}])
        with self.patch_conn(cursor):
            self.assertEqual(pg_service.find_document_by_hash("hash-1", "class-1"), {"id": "doc-1"})
        self.assertIn("class_id IS NOT DISTINCT FROM", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1], ("hash-1", "class-1"))

        cursor = FakeCursor(fetchone_results=[None])
        with self.patch_conn(cursor):
            self.assertIsNone(pg_service.find_document_by_hash("hash-2", "class-2"))

        cursor = FakeCursor(fetchone_results=[{"id": "doc-3"}])
        with patch("app.services.pg.pg_retrieval_service._get_conn", return_value=FakeConnection(cursor)) as get_conn:
            self.assertEqual(pg_service.find_document_by_hash("hash-3", "class-3", user_id="teacher-1"), {"id": "doc-3"})
        get_conn.assert_called_once_with("teacher-1")

    def test_create_graph_from_document_uses_requested_embedding_columns(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "teacher-1", "can_manage": True},
                {"id": "doc-1"},
            ]
        )
        document = {
            "hash": "hash-1",
            "name": "lesson.pdf",
            "size": 12,
            "mimetype": "application/pdf",
            "class_id": "class-1",
        }
        chunks = [
            {"text": "A", "metadata": {"pageNumber": 2}, "embedding": [0.1]},
            {"text": "B", "embedding": [0.3]},
        ]

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values:
            result = pg_service.create_graph_from_document(
                document,
                chunks,
                user_id="teacher-1",
            )

        self.assertEqual(result, {"fileId": "doc-1", "isNew": True})
        rows = execute_values.call_args.args[2]
        self.assertEqual(rows[0][0:5], ("doc-1", 2, 2, 0, "A"))
        self.assertEqual(rows[1][0:5], ("doc-1", 1, 1, 1, "B"))
        self.assertIn("SELECT set_config", cursor.executed[0][0])
        self.assertIn("can_manage_document_class", cursor.executed[1][0])
        self.assertIn("ON CONFLICT (class_id, hash) DO NOTHING", cursor.executed[2][0])

    def test_create_graph_from_document_stores_image_media_after_chunk_insert(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "teacher-1", "can_manage": True},
                {"id": "doc-1"},
            ],
            fetchall_results=[[{"id": "chunk-1", "chunk_index": 0}]],
        )
        calls = []

        def fake_execute_values(cur, sql, rows, template=None):
            calls.append({"sql": sql, "rows": rows, "template": template})

        document = {
            "hash": "hash-image",
            "name": "slides.pdf",
            "size": 12,
            "mimetype": "application/pdf",
            "class_id": "class-1",
        }
        chunks = [{
            "text": "Image source: slides.pdf (page 2, image 1)",
            "metadata": {"pageNumber": 2, "imageIndex": 1},
            "embedding": [0.1],
            "image_data": b"image-bytes",
            "image_mimetype": "image/png",
        }]

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values",
            side_effect=fake_execute_values,
        ):
            result = pg_service.create_graph_from_document(
                document,
                chunks,
                user_id="teacher-1",
            )

        self.assertEqual(result, {"fileId": "doc-1", "isNew": True})
        self.assertEqual(len(calls), 2)
        self.assertIn("INSERT INTO chunk_media", calls[1]["sql"])
        self.assertEqual(calls[1]["rows"], [("chunk-1", "image/png", b"image-bytes")])
        self.assertIn("SELECT id, chunk_index FROM chunks", cursor.executed[-1][0])

    def test_create_graph_from_document_fails_when_inserted_media_chunk_is_missing(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "teacher-1", "can_manage": True},
                {"id": "doc-1"},
            ],
            fetchall_results=[[]],
        )
        document = {
            "hash": "hash-image-missing",
            "name": "slides.pdf",
            "size": 12,
            "mimetype": "application/pdf",
            "class_id": "class-1",
        }
        chunks = [{
            "text": "Image",
            "metadata": {"pageNumber": 1},
            "embedding": [0.1],
            "image_data": b"image-bytes",
            "image_mimetype": "image/png",
        }]

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values"
        ):
            with self.assertRaises(RuntimeError) as error:
                pg_service.create_graph_from_document(document, chunks, user_id="teacher-1")

        self.assertEqual(error.exception.stage, "chunks")

    def test_create_graph_from_document_without_class_id_uses_default_embedding_column(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-2"}])
        document = {"hash": "hash-2", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf"}
        chunks = [{"text": "Only", "metadata": {}, "embedding": [0.4]}]

        with self.patch_conn(cursor), patch("app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values") as execute_values:
            pg_service.create_graph_from_document(document, chunks)

        self.assertIn("INSERT INTO documents (hash, name, size_bytes, mimetype)", cursor.executed[0][0])
        self.assertNotIn("ON CONFLICT", cursor.executed[0][0])
        self.assertEqual(execute_values.call_args.args[2][0][5], "[0.40000000]")

    def test_create_graph_from_document_marks_document_and_chunk_write_failures(self):
        document = {"hash": "hash-1", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf", "class_id": "class-1"}
        chunks = [{"text": "Only", "metadata": {}, "embedding": [0.4]}]

        cursor = FakeCursor(fetchone_results=[{"session_user_id": "context-user", "can_manage": True}])
        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_documents.insert_document",
            side_effect=RuntimeError("document database error"),
        ):
            with self.assertRaises(RuntimeError) as document_error:
                pg_service.create_graph_from_document(document, chunks)
        self.assertEqual(document_error.exception.stage, "document")

        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "context-user", "can_manage": True},
                {"id": "doc-1"},
            ]
        )
        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values",
            side_effect=RuntimeError("chunk database error"),
        ):
            with self.assertRaises(RuntimeError) as chunk_error:
                pg_service.create_graph_from_document(document, chunks)
        self.assertEqual(chunk_error.exception.stage, "chunks")

    def test_create_graph_from_document_reuses_racing_duplicate_without_inserting_chunks(self):
        document = {"hash": "hash-1", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf", "class_id": "class-1"}
        chunks = [{"text": "Only", "metadata": {}, "embedding": [0.4]}]
        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "teacher-1", "can_manage": True},
                None,
                {"id": "existing-doc"},
            ]
        )

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values, patch(
            "app.services.pg.pg_retrieval_documents.logger"
        ) as logger:
            result = pg_service.create_graph_from_document(document, chunks, user_id="teacher-1")

        self.assertEqual(result, {"fileId": "existing-doc", "isNew": False})
        self.assertEqual(len(cursor.executed), 4)
        self.assertIn("ON CONFLICT (class_id, hash) DO NOTHING", cursor.executed[2][0])
        logger.info.assert_called_once()
        self.assertIn("Document write RLS context", logger.info.call_args.args[0])
        self.assertIn("SELECT id FROM documents", cursor.executed[3][0])
        execute_values.assert_not_called()

    def test_create_graph_from_document_rejects_mismatched_rls_context(self):
        document = {"hash": "hash-1", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf", "class_id": "class-1"}
        cursor = FakeCursor(fetchone_results=[{"session_user_id": "other-user", "can_manage": True}])

        with self.patch_conn(cursor):
            with self.assertRaises(RuntimeError) as error:
                pg_service.create_graph_from_document(document, [], user_id="teacher-1")

        self.assertEqual(error.exception.stage, "document")
        self.assertEqual(len(cursor.executed), 2)

    def test_create_graph_from_document_marks_unreadable_conflict_as_document_failure(self):
        document = {"hash": "hash-1", "name": "lesson.pdf", "size": 12, "mimetype": "application/pdf", "class_id": "class-1"}
        cursor = FakeCursor(
            fetchone_results=[
                {"session_user_id": "teacher-1", "can_manage": True},
                None,
                None,
            ]
        )

        with self.patch_conn(cursor):
            with self.assertRaises(RuntimeError) as error:
                pg_service.create_graph_from_document(document, [], user_id="teacher-1")

        self.assertEqual(error.exception.stage, "document")
        self.assertIn("conflict could not be read", str(error.exception.cause).lower())

    def test_retrieve_graph_context_uses_default_and_v2_query_shapes(self):
        rows = [{"text": "chunk", "score": 0.4, "source": "doc", "page_start": 2, "fileid": "file-1", "chunkid": "chunk-1"}]
        cursor = FakeCursor(fetchall_results=[rows])
        with self.patch_conn(cursor):
            result = pg_service.retrieve_graph_context([0.1], selected_file_ids=["file-1"])

        self.assertEqual(result[0]["fileId"], "file-1")
        self.assertIn("IS NOT NULL", cursor.executed[0][0])

        cursor = FakeCursor(fetchall_results=[rows])
        with self.patch_conn(cursor):
            pg_service.retrieve_graph_context([0.1], selected_file_ids=["file-1"])
        self.assertIn("embedding IS NOT NULL", cursor.executed[0][0])


    def test_get_fulltext_search_backend_rejects_unknown_backend(self):
        with patch(
            "app.services.pg.pg_retrieval_service.get_settings",
            return_value=make_settings(fulltext_search_backend="bad"),
        ):
            with self.assertRaises(ValueError):
                pg_service._get_fulltext_search_backend()
