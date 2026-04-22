import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.utils.dev_credentials import (
    MissingCredentialError,
    _first_llm_api_key,
    get_eval_embedding_credentials,
    get_eval_llm_credentials,
    get_llm_credentials,
)


def make_settings(**overrides):
    values = {
        "llm_api_keys": "",
        "llm_api_key": "",
        "llm_base_url": "",
        "eval_llm_api_key": "",
        "eval_llm_base_url": "",
        "eval_llm_model": "",
        "eval_embedding_api_key": "",
        "eval_embedding_base_url": "",
        "eval_embedding_model": "",
        "embedding_api_key": "",
        "embedding_base_url": "",
        "embedding_model": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class DevCredentialsTests(unittest.TestCase):
    def test_first_llm_api_key_prefers_explicit_key(self):
        settings = make_settings(llm_api_key="direct-key", llm_api_keys="pool-1,pool-2")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            self.assertEqual(_first_llm_api_key(), "direct-key")

    def test_get_llm_credentials_prefers_explicit_key(self):
        settings = make_settings(llm_api_key="direct-key", llm_base_url="https://example.com")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_llm_credentials()

        self.assertEqual(creds.api_key, "direct-key")
        self.assertEqual(creds.base_url, "https://example.com")

    def test_get_llm_credentials_falls_back_to_first_pool_key(self):
        settings = make_settings(llm_api_keys=" key-1 , key-2 ")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_llm_credentials()

        self.assertEqual(creds.api_key, "key-1")
        self.assertIsNone(creds.base_url)

    def test_get_llm_credentials_raises_when_missing(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings()):
            with self.assertRaises(MissingCredentialError):
                get_llm_credentials()

    def test_get_eval_llm_credentials_uses_defaults(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings(eval_llm_api_key="llm-key")):
            creds = get_eval_llm_credentials()

        self.assertEqual(creds.api_key, "llm-key")
        self.assertEqual(creds.base_url, "https://www.chataiapi.com/v1")
        self.assertEqual(creds.model, "gemini-2.5-flash")

    def test_get_eval_llm_credentials_raises_when_missing(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings()):
            with self.assertRaises(MissingCredentialError):
                get_eval_llm_credentials()

    def test_get_eval_embedding_credentials_prefers_eval_settings(self):
        settings = make_settings(
            eval_embedding_api_key="embed-key",
            eval_embedding_base_url="https://embed.example",
            eval_embedding_model="embed-model",
        )
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_eval_embedding_credentials()

        self.assertEqual(creds.api_key, "embed-key")
        self.assertEqual(creds.base_url, "https://embed.example")
        self.assertEqual(creds.model, "embed-model")

    def test_get_eval_embedding_credentials_falls_back_to_runtime_embedding_settings(self):
        settings = make_settings(
            embedding_api_key="runtime-key",
            embedding_base_url="https://runtime.example",
            embedding_model="runtime-model",
        )
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_eval_embedding_credentials()

        self.assertEqual(creds.api_key, "runtime-key")
        self.assertEqual(creds.base_url, "https://runtime.example")
        self.assertEqual(creds.model, "runtime-model")

    def test_get_eval_embedding_credentials_falls_back_to_llm_settings(self):
        settings = make_settings(
            llm_api_key="shared-key",
            llm_base_url="https://shared.example",
        )
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_eval_embedding_credentials()

        self.assertEqual(creds.api_key, "shared-key")
        self.assertEqual(creds.base_url, "https://shared.example")
        self.assertEqual(creds.model, "google/gemini-embedding-001")

    def test_get_eval_embedding_credentials_raises_when_missing(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings()):
            with self.assertRaises(MissingCredentialError):
                get_eval_embedding_credentials()
