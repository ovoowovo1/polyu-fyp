from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

from app.utils.api_key_manager import OpenAIEmbeddings
from app.utils.ingest_errors import EmbeddingProviderError


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.reason = "OK"

    def json(self):
        return self._payload


def make_settings():
    return SimpleNamespace(
        openai_embedding_api_key="test-key",
        openai_embedding_base_url="https://openrouter.ai/api/v1",
        openai_embedding_model="google/gemini-embedding-001",
        google_ai_model="gemini-2.5-flash",
    )


class EmbeddingClientTests(unittest.TestCase):
    def test_openrouter_error_payload_becomes_structured_exception(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=make_settings()), patch(
            "app.utils.api_key_manager.requests.post",
            return_value=FakeResponse(
                200,
                {"error": {"message": "No successful provider responses.", "code": 404}},
            ),
        ):
            client = OpenAIEmbeddings()

            with self.assertRaises(EmbeddingProviderError) as ctx:
                client.embed_documents(["hello world"])

        error = ctx.exception
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertTrue(error.retryable)
        self.assertEqual(error.provider, "openrouter")
        self.assertEqual(error.http_status, 200)
        self.assertEqual(error.upstream_code, 404)
        self.assertIn("No successful provider responses", error.upstream_message)
        self.assertIn("\"error\"", error.raw_preview)

    def test_no_endpoints_found_is_retryable_for_fallback(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=make_settings()), patch(
            "app.utils.api_key_manager.requests.post",
            return_value=FakeResponse(
                200,
                {"error": {"message": "No endpoints found for google/gemini-embedding-001.", "code": 404}},
            ),
        ):
            client = OpenAIEmbeddings()

            with self.assertRaises(EmbeddingProviderError) as ctx:
                client.embed_documents(["hello world"])

        error = ctx.exception
        self.assertEqual(error.code, "EMBEDDING_UPSTREAM_FAILED")
        self.assertTrue(error.retryable)
        self.assertEqual(error.upstream_code, 404)
        self.assertIn("No endpoints found", error.upstream_message)

    def test_invalid_embedding_count_raises_response_invalid(self):
        with patch("app.utils.api_key_manager.get_settings", return_value=make_settings()), patch(
            "app.utils.api_key_manager.requests.post",
            return_value=FakeResponse(
                200,
                {
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    ]
                },
            ),
        ):
            client = OpenAIEmbeddings()

            with self.assertRaises(EmbeddingProviderError) as ctx:
                client.embed_documents(["first", "second"])

        error = ctx.exception
        self.assertEqual(error.code, "EMBEDDING_RESPONSE_INVALID")
        self.assertTrue(error.retryable)
        self.assertIn("count mismatch", error.message)
