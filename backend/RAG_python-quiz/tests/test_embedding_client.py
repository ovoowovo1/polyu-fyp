from unittest.mock import patch
import unittest

from app.utils.api_key_manager import OpenAIEmbeddings
from app.utils.ingest_errors import EmbeddingProviderError
from tests.support import FakeResponse, make_embedding_settings


def embedding_error_for(response_payload, documents=None):
    with patch("app.utils.api_key_manager.get_settings", return_value=make_embedding_settings()), patch(
        "app.utils.api_key_manager.requests.post",
        return_value=FakeResponse(200, response_payload),
    ):
        client = OpenAIEmbeddings()
        with unittest.TestCase().assertRaises(EmbeddingProviderError) as ctx:
            client.embed_documents(documents or ["hello world"])

    return ctx.exception


class EmbeddingClientTests(unittest.TestCase):
    def test_openrouter_error_payload_becomes_structured_exception(self):
        error = embedding_error_for({"error": {"message": "No successful provider responses.", "code": 404}})
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertTrue(error.retryable)
        self.assertEqual(error.provider, "openrouter")
        self.assertEqual(error.http_status, 200)
        self.assertEqual(error.upstream_code, 404)
        self.assertIn("No successful provider responses", error.upstream_message)
        self.assertIn("\"error\"", error.raw_preview)

    def test_no_endpoints_found_is_retryable_for_fallback(self):
        error = embedding_error_for({"error": {"message": "No endpoints found for google/gemini-embedding-001.", "code": 404}})
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertTrue(error.retryable)
        self.assertEqual(error.upstream_code, 404)
        self.assertIn("No endpoints found", error.upstream_message)

    def test_invalid_embedding_count_raises_response_invalid(self):
        error = embedding_error_for(
            {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
            documents=["first", "second"],
        )
        self.assertEqual(error.code, "EMBEDDING_RESPONSE_INVALID")
        self.assertTrue(error.retryable)
        self.assertIn("count mismatch", error.message)
