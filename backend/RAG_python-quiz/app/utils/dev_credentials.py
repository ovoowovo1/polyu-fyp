from dataclasses import dataclass
from typing import Optional

from app.config import get_settings


class MissingCredentialError(RuntimeError):
    """Raised when a manual smoke script or evaluation utility lacks credentials."""


@dataclass(frozen=True)
class GenAICredentials:
    api_key: str
    base_url: Optional[str]


@dataclass(frozen=True)
class OpenAICompatibleCredentials:
    api_key: str
    base_url: str
    model: str


def _first_google_api_key() -> str:
    settings = get_settings()
    keys = [key.strip() for key in (settings.google_api_key_list or "").split(",") if key.strip()]
    return keys[0] if keys else ""


def get_genai_credentials() -> GenAICredentials:
    settings = get_settings()
    api_key = settings.genai_api_key or _first_google_api_key()
    if not api_key:
        raise MissingCredentialError(
            "Missing GenAI credentials. Set GENAI_API_KEY or GOOGLE_API_KEY_LIST in .env or the shell environment."
        )

    base_url = settings.genai_base_url.strip() or None
    return GenAICredentials(api_key=api_key, base_url=base_url)


def get_eval_llm_credentials() -> OpenAICompatibleCredentials:
    settings = get_settings()
    api_key = settings.eval_llm_api_key.strip()
    if not api_key:
        raise MissingCredentialError(
            "Missing evaluation LLM credentials. Set EVAL_LLM_API_KEY in .env or the shell environment."
        )

    base_url = settings.eval_llm_base_url.strip() or "https://www.chataiapi.com/v1"
    model = settings.eval_llm_model.strip() or "gemini-2.5-flash"
    return OpenAICompatibleCredentials(api_key=api_key, base_url=base_url, model=model)


def get_eval_embedding_credentials() -> OpenAICompatibleCredentials:
    settings = get_settings()
    api_key = settings.eval_embedding_api_key.strip() or settings.openai_embedding_api_key.strip()
    if not api_key:
        raise MissingCredentialError(
            "Missing evaluation embedding credentials. Set EVAL_EMBEDDING_API_KEY or OPENAI_EMBEDDING_API_KEY in "
            ".env or the shell environment."
        )

    base_url = (
        settings.eval_embedding_base_url.strip()
        or settings.openai_embedding_base_url.strip()
        or "https://openrouter.ai/api/v1"
    )
    model = (
        settings.eval_embedding_model.strip()
        or settings.openai_embedding_model.strip()
        or "google/gemini-embedding-001"
    )
    return OpenAICompatibleCredentials(api_key=api_key, base_url=base_url, model=model)
