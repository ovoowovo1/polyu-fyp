from unittest.mock import patch
from types import SimpleNamespace

from app.services.pg import pg_retrieval_service as pg_service
from app.services.pg import pg_retrieval_documents
from app.services.pg import pg_shared
from tests.pg_service_test_support import PgServiceBase
from tests.support import FakeConnection, FakeCursor, make_settings


class PgRetrievalServiceTests(PgServiceBase):
    module_path = "app.services.pg.pg_retrieval_service"

    def test_to_pgvector_formats_float_sequence(self):
        self.assertEqual(pg_shared._to_pgvector([1, 2.5]), "[1.00000000,2.50000000]")

    def test_get_embedding_column_uses_settings_and_rejects_invalid_values(self):
        with patch(
            "app.services.pg.pg_shared.get_settings",
            return_value=make_settings(embedding_active_column="embedding_v2"),
        ):
            self.assertEqual(pg_shared._get_embedding_column(), "embedding_v2")

        with self.assertRaises(ValueError):
            pg_shared._get_embedding_column("invalid")

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
            {"text": "A", "metadata": {"pageNumber": 2}, "embedding": [0.1], "embedding_v2": [0.2]},
            {"text": "B", "embedding": [0.3], "embedding_v2": None},
        ]

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values:
            result = pg_service.create_graph_from_document(
                document,
                chunks,
                embedding_column="embedding",
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

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_shared.get_settings",
            return_value=make_settings(),
        ), patch("app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values") as execute_values:
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
        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_shared.get_settings",
            return_value=make_settings(),
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

        with patch("app.services.pg.pg_retrieval_service.redis_cache.invalidate_namespaces") as invalidate:
            self.assertEqual(pg_service.update_chunk_embeddings([]), 0)
        invalidate.assert_not_called()

        cursor = FakeCursor()
        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values, patch(
            "app.services.pg.pg_retrieval_service.redis_cache.invalidate_namespaces"
        ) as invalidate:
            updated = pg_service.update_chunk_embeddings([{"id": "chunk-1", "embedding": [0.9]}])
        self.assertEqual(updated, 1)
        self.assertEqual(execute_values.call_args.args[2], [("chunk-1", "[0.90000000]")])
        invalidate.assert_called_once_with("rag:retrieval")

    def test_retrieve_context_helpers_cover_empty_and_keyword_paths(self):
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

    def test_retrieve_context_by_keywords_can_use_postgres_fulltext_backend(self):
        cursor = FakeCursor(
            fetchall_results=[
                [{"text": "chunk", "score": 0.5, "source": "lesson.pdf", "page_start": 1, "fileid": "file-1", "chunkid": "chunk-1"}],
            ]
        )

        with self.patch_conn(cursor), patch(
            "app.services.pg.pg_retrieval_service.get_settings",
            return_value=make_settings(fulltext_search_backend="postgres"),
        ):
            result = pg_service.retrieve_context_by_keywords("sql injection", selected_file_ids=["file-1"], k=3)

        self.assertEqual(result[0]["score"], 0.5)
        sql, params = cursor.executed[0]
        self.assertIn("websearch_to_tsquery('simple', %s)", sql)
        self.assertIn("similarity(COALESCE(c.entities_json::text, ''), query.raw_query)", sql)
        self.assertNotIn("paradedb.score", sql)
        self.assertNotIn("@@@", sql)
        self.assertEqual(params, ["sql injection", "sql injection", ["file-1"], 3])

    def test_get_fulltext_search_backend_rejects_unknown_backend(self):
        with patch(
            "app.services.pg.pg_retrieval_service.get_settings",
            return_value=make_settings(fulltext_search_backend="bad"),
        ):
            with self.assertRaises(ValueError):
                pg_service._get_fulltext_search_backend()
