from pathlib import Path


def test_single_embedding_migration_guards_against_data_loss():
    sql = (Path(__file__).resolve().parents[1] / "migrations/use_single_embedding.sql").read_text()
    assert "ACCESS EXCLUSIVE" in sql
    assert "RAISE EXCEPTION" in sql
    assert "DROP COLUMN IF EXISTS embedding_v2" in sql
    assert "vector(3072)" in sql
    assert "DELETE FROM" not in sql
