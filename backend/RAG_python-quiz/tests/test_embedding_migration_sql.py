from pathlib import Path
import unittest


class EmbeddingMigrationSqlTests(unittest.TestCase):
    def test_add_chunks_embedding_v2_migration_adds_expected_column(self):
        migration_path = Path(__file__).resolve().parents[1] / "migrations" / "add_chunks_embedding_v2.sql"
        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn("ADD COLUMN IF NOT EXISTS embedding_v2 vector(3072)", sql)
