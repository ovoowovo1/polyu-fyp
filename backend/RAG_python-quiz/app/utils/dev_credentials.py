from dataclasses import dataclass

from app.config import get_settings


class MissingCredentialError(RuntimeError):
    """Raised when a manual smoke script or evaluation utility lacks credentials."""


@dataclass(frozen=True)
class OpenAICompatibleCredentials:
    api_key: str
    base_url: str
    model: str


def _first_llm_api_key(settings=None) -> str:
    settings = settings or get_settings()
    return settings.llm_api_key.strip() or next(
        (key.strip() for key in (settings.llm_api_keys or "").split(",") if key.strip()),
        "",
    )


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
    api_key = (
        settings.eval_embedding_api_key.strip()
        or settings.embedding_api_key.strip()
        or _first_llm_api_key(settings)
    )
    if not api_key:
        raise MissingCredentialError(
            "Missing evaluation embedding credentials. Set EVAL_EMBEDDING_API_KEY, EMBEDDING_API_KEY, "
            "LLM_API_KEY, or LLM_API_KEYS in .env or the shell environment."
        )

    base_url = (
        settings.eval_embedding_base_url.strip()
        or settings.embedding_base_url.strip()
        or settings.llm_base_url.strip()
        or "https://openrouter.ai/api/v1"
    )
    model = (
        settings.eval_embedding_model.strip()
        or settings.embedding_model.strip()
        or "google/gemini-embedding-001"
    )
    return OpenAICompatibleCredentials(api_key=api_key, base_url=base_url, model=model)
