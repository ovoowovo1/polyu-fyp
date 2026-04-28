import unittest
from unittest.mock import patch

from app.services import pg_service
from tests.pg_service_test_support import PgServiceBase
from tests.support import FakeCursor


class PgRetrievalServiceTests(PgServiceBase):
    module_path = "app.services.pg_retrieval_service"

    def test_to_pgvector_formats_float_sequence(self):
        self.assertEqual(pg_service._to_pgvector([1, 2.5]), "[1.00000000,2.50000000]")

    def test_get_embedding_column_uses_settings_and_rejects_invalid_values(self):
        with patch(
            "app.services.pg_shared.get_settings",
            return_value=type("Settings", (), {"embedding_active_column": "embedding_v2"})(),
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

        with self.patch_conn(cursor), patch(
            "app.services.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values:
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
            "app.services.pg_shared.get_settings",
            return_value=type("Settings", (), {"embedding_active_column": "embedding"})(),
        ), patch("app.services.pg_retrieval_service.psycopg2.extras.execute_values") as execute_values:
            pg_service.create_graph_from_document(document, chunks)

        self.assertIn("INSERT INTO documents (hash, name, size_bytes, mimetype)", cursor.executed[0][0])
        self.assertEqual(execute_values.call_args.args[2][0][5], "[0.40000000]")

    def test_retrieve_graph_context_uses_default_and_v2_query_shapes(self):
        rows = [{"text": "chunk", "score": 0.4, "source": "doc", "page_start": 2, "fileid": "file-1", "chunkid": "chunk-1"}]
        cursor = FakeCursor(fetchall_results=[rows])
        with self.patch_conn(cursor), patch(
            "app.services.pg_shared.get_settings",
            return_value=type("Settings", (), {"embedding_active_column": "embedding"})(),
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
        with self.patch_conn(cursor), patch(
            "app.services.pg_retrieval_service.psycopg2.extras.execute_values"
        ) as execute_values:
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
