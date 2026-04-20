import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.utils.dev_credentials import (
    MissingCredentialError,
    get_eval_embedding_credentials,
    get_eval_llm_credentials,
    get_genai_credentials,
)


def make_settings(**overrides):
    values = {
        "google_api_key_list": "",
        "genai_api_key": "",
        "genai_base_url": "",
        "eval_llm_api_key": "",
        "eval_llm_base_url": "",
        "eval_llm_model": "",
        "eval_embedding_api_key": "",
        "eval_embedding_base_url": "",
        "eval_embedding_model": "",
        "openai_embedding_api_key": "",
        "openai_embedding_base_url": "",
        "openai_embedding_model": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class DevCredentialsTests(unittest.TestCase):
    def test_get_genai_credentials_prefers_explicit_key(self):
        settings = make_settings(genai_api_key="direct-key", genai_base_url="https://example.com")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_genai_credentials()

        self.assertEqual(creds.api_key, "direct-key")
        self.assertEqual(creds.base_url, "https://example.com")

    def test_get_genai_credentials_falls_back_to_first_google_key(self):
        settings = make_settings(google_api_key_list=" key-1 , key-2 ")
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_genai_credentials()

        self.assertEqual(creds.api_key, "key-1")
        self.assertIsNone(creds.base_url)

    def test_get_genai_credentials_raises_when_missing(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings()):
            with self.assertRaises(MissingCredentialError):
                get_genai_credentials()

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
            openai_embedding_api_key="runtime-key",
            openai_embedding_base_url="https://runtime.example",
            openai_embedding_model="runtime-model",
        )
        with patch("app.utils.dev_credentials.get_settings", return_value=settings):
            creds = get_eval_embedding_credentials()

        self.assertEqual(creds.api_key, "runtime-key")
        self.assertEqual(creds.base_url, "https://runtime.example")
        self.assertEqual(creds.model, "runtime-model")

    def test_get_eval_embedding_credentials_raises_when_missing(self):
        with patch("app.utils.dev_credentials.get_settings", return_value=make_settings()):
            with self.assertRaises(MissingCredentialError):
                get_eval_embedding_credentials()
