import asyncio
from unittest.mock import patch
import unittest

from app.utils.api_key_manager import OpenAIEmbeddings
from app.utils.runtime import embeddings as embedding_runtime
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

    def test_image_embedding_payload_uses_openrouter_multimodal_format(self):
        self.assertEqual(
            embedding_runtime.image_bytes_to_data_url(b"img", "image/png"),
            "data:image/png;base64,aW1n",
        )

        captured = {}

        def fake_post(endpoint, *, json, headers, timeout):
            captured["endpoint"] = endpoint
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return FakeResponse(
                payload={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
                text='{"data": "..."}',
            )

        with patch("app.utils.api_key_manager.get_settings", return_value=make_embedding_settings()), patch(
            "app.utils.api_key_manager.OpenAI",
            return_value="openai-client",
        ), patch("app.utils.api_key_manager.requests.post", side_effect=fake_post):
            client = OpenAIEmbeddings()
            vectors = client.embed_images([{"content": b"img", "mime_type": "image/png"}])

        self.assertEqual(vectors, [[0.1, 0.2, 0.3]])
        self.assertEqual(captured["json"]["model"], "google/gemini-embedding-001")
        self.assertEqual(captured["json"]["encoding_format"], "float")
        image_input = captured["json"]["input"][0]
        self.assertEqual(image_input["content"][0]["type"], "image_url")
        self.assertEqual(image_input["content"][0]["image_url"]["url"], "data:image/png;base64,aW1n")

        with patch.object(client, "embed_images", return_value=[[0.9]]):
            self.assertEqual(asyncio.run(client.aembed_images([{"content": b"x", "mime_type": "image/png"}])), [[0.9]])
