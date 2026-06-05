import unittest
from unittest.mock import patch

from app.utils.dev_credentials import (
    MissingCredentialError,
    _first_llm_api_key,
    get_eval_embedding_credentials,
    get_eval_llm_credentials,
)
from tests.support import make_settings


class DevCredentialsTests(unittest.TestCase):
    def test_first_llm_api_key_prefers_explicit_key(self):
        settings = make_settings(llm_api_key="direct-key", llm_api_keys="pool-1,pool-2")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            self.assertEqual(_first_llm_api_key(), "direct-key")

    def test_get_eval_llm_credentials_uses_defaults(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings(eval_llm_api_key="llm-key")):
            creds = get_eval_llm_credentials()

        self.assertEqual(creds.api_key, "llm-key")
        self.assertEqual(creds.base_url, "https://www.chataiapi.com/v1")
        self.assertEqual(creds.model, "gemini-2.5-flash")

    def test_get_eval_embedding_credentials_resolves_source_priority(self):
        cases = (
            (
                make_settings(
                    eval_embedding_api_key="embed-key",
                    eval_embedding_base_url="https://embed.example",
                    eval_embedding_model="embed-model",
                ),
                ("embed-key", "https://embed.example", "embed-model"),
            ),
            (
                make_settings(
                    embedding_api_key="runtime-key",
                    embedding_base_url="https://runtime.example",
                    embedding_model="runtime-model",
                ),
                ("runtime-key", "https://runtime.example", "runtime-model"),
            ),
            (
                make_settings(llm_api_key="shared-key", llm_base_url="https://shared.example"),
                ("shared-key", "https://shared.example", "google/gemini-embedding-001"),
            ),
        )
        for settings, expected in cases:
            with self.subTest(expected=expected), patch("app.utils.dev_credentials.get_settings", return_value=settings):
                creds = get_eval_embedding_credentials()
            self.assertEqual((creds.api_key, creds.base_url, creds.model), expected)

    def test_eval_credentials_raise_when_missing(self):
        for getter in (get_eval_llm_credentials, get_eval_embedding_credentials):
            with self.subTest(getter=getter.__name__), patch(
                "app.utils.dev_credentials.get_settings",
                return_value=make_settings(),
            ):
                with self.assertRaises(MissingCredentialError):
                    getter()
