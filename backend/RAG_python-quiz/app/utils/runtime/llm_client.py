from __future__ import annotations

from typing import Optional

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_llm_base_url(settings) -> str:
    return (settings.llm_base_url.strip() or OPENROUTER_BASE_URL).rstrip("/")


def default_llm_model_name(settings) -> str:
    return settings.llm_model or "gemini-2.5-flash"


def create_llm_client(*, api_key: Optional[str], settings, openai_cls):
    if not api_key:
        raise RuntimeError("No LLM API key configured")
    return openai_cls(
        base_url=resolve_llm_base_url(settings),
        api_key=api_key,
    )
