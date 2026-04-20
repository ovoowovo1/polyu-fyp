import unittest

from app.utils import ingest_errors


class IngestErrorsTests(unittest.TestCase):
    def test_compact_text_covers_json_repr_blank_and_truncation_paths(self):
        self.assertEqual(ingest_errors._compact_text({"a": 1}), '{"a": 1}')
        self.assertIn("{'a': {1}}", ingest_errors._compact_text({"a": {1}}))
        self.assertIsNone(ingest_errors._compact_text("   \n  "))
        self.assertEqual(ingest_errors._compact_text("abcdef", limit=5), "ab...")

    def test_document_ingest_error_to_dict_includes_details_when_present(self):
        error = ingest_errors.DocumentIngestError(
            code="INGEST_FAILED",
            message="failed",
            details="more info",
        )

        self.assertEqual(
            error.to_dict(),
            {"code": "INGEST_FAILED", "message": "failed", "details": "more info"},
        )
