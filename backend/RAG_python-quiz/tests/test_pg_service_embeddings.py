from unittest.mock import patch
import unittest

from app.services.pg import pg_retrieval_service as pg_service
from tests.support import FakeConnection, FakeCursor, capture_execute_values, make_embedding_settings

EMBEDDING_SETTINGS = make_embedding_settings()


class PgServiceEmbeddingColumnTests(unittest.TestCase):
    def test_create_graph_from_document_uses_active_embedding_column(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-1"}])
        conn = FakeConnection(cursor)
        captured, fake_execute_values = capture_execute_values()

        with patch("app.services.pg.pg_shared.get_settings", return_value=EMBEDDING_SETTINGS), patch(
            "app.services.pg.pg_retrieval_service._get_conn",
            return_value=conn,
        ), patch("app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values", side_effect=fake_execute_values):
            result = pg_service.create_graph_from_document(
                {"hash": "hash", "name": "doc.pdf", "size": 12, "mimetype": "application/pdf"},
                [{"text": "chunk text", "metadata": {"pageNumber": 2}, "embedding": [0.1, 0.2]}],
            )

        self.assertEqual(result, {"fileId": "doc-1"})
        self.assertIn("embedding_v2", captured["sql"])
        self.assertEqual(captured["template"], "(%s,%s,%s,%s,%s,%s::vector)")
        self.assertTrue(conn.committed)

    def test_retrieve_graph_context_uses_embedding_v2_and_filters_nulls(self):
        cursor = FakeCursor(
            fetchall_results=[
                [
                    {
                        "text": "chunk text",
                        "score": 0.12,
                        "source": "doc.pdf",
                        "page_start": 1,
                        "fileid": "file-1",
                        "chunkid": "chunk-1",
                    }
                ]
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_shared.get_settings", return_value=EMBEDDING_SETTINGS), patch(
            "app.services.pg.pg_retrieval_service._get_conn",
            return_value=conn,
        ):
            rows = pg_service.retrieve_graph_context([0.1, 0.2], k=5, selected_file_ids=["file-1"])

        sql = cursor.executed[0][0]
        self.assertIn("c.embedding_v2 IS NOT NULL", sql)
        self.assertIn("ORDER BY c.embedding_v2 <=> %s::vector", sql)
        self.assertEqual(rows[0]["chunkId"], "chunk-1")

    def test_retrieve_graph_context_can_use_legacy_embedding_column(self):
        cursor = FakeCursor(fetchall_results=[[]])
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_retrieval_service._get_conn", return_value=conn):
            pg_service.retrieve_graph_context([0.1], embedding_column="embedding")

        sql = cursor.executed[0][0]
        self.assertNotIn("IS NOT NULL", sql)
        self.assertIn("ORDER BY c.embedding <=> %s::vector", sql)

    def test_create_graph_from_document_can_insert_primary_and_standby_embeddings(self):
        cursor = FakeCursor(fetchone_results=[{"id": "doc-1"}])
        conn = FakeConnection(cursor)
        captured, fake_execute_values = capture_execute_values()

        with patch("app.services.pg.pg_retrieval_service._get_conn", return_value=conn), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values",
            side_effect=fake_execute_values,
        ):
            pg_service.create_graph_from_document(
                {"hash": "hash", "name": "doc.pdf", "size": 12, "mimetype": "application/pdf"},
                [
                    {
                        "text": "chunk text",
                        "metadata": {"pageNumber": 2},
                        "embedding": [0.1, 0.2],
                        "embedding_v2": [0.3, 0.4],
                    }
                ],
            )

        self.assertIn("embedding, embedding_v2", captured["sql"])
        self.assertEqual(captured["template"], "(%s,%s,%s,%s,%s,%s::vector,%s::vector)")
        self.assertEqual(len(captured["rows"][0]), 7)

    def test_update_chunk_embeddings_targets_requested_column(self):
        cursor = FakeCursor()
        conn = FakeConnection(cursor)
        captured, fake_execute_values = capture_execute_values()

        with patch("app.services.pg.pg_retrieval_service._get_conn", return_value=conn), patch(
            "app.services.pg.pg_retrieval_service.psycopg2.extras.execute_values",
            side_effect=fake_execute_values,
        ):
            updated = pg_service.update_chunk_embeddings(
                [{"id": "00000000-0000-0000-0000-000000000001", "embedding": [0.5, 0.6]}],
                embedding_column="embedding_v2",
            )

        self.assertEqual(updated, 1)
        self.assertIn("SET embedding_v2 = payload.embedding::vector", captured["sql"])
        self.assertEqual(len(captured["rows"]), 1)
        self.assertTrue(conn.committed)
