# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, List, Optional, Type
from urllib.parse import urlparse

import requests
from fastapi import HTTPException
from langchain_google_genai import ChatGoogleGenerativeAI
from openai import OpenAI

from app.config import get_settings
from app.logger import get_logger
from app.utils.ingest_errors import EmbeddingProviderError

logger = get_logger(__name__)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_TIMEOUT_SECONDS = 120
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

_llm_keys: List[str] = []
_llm_index = 0


def _split_api_keys(raw_value: str) -> List[str]:
    return [key.strip() for key in (raw_value or "").split(",") if key.strip()]


def _first_csv_key(raw_value: str) -> str:
    keys = _split_api_keys(raw_value)
    return keys[0] if keys else ""


def _get_llm_runtime_keys(settings=None) -> List[str]:
    settings = settings or get_settings()
    if settings.llm_api_key.strip():
        return [settings.llm_api_key.strip()]
    return _split_api_keys(settings.llm_api_keys)


def _first_configured_llm_key(settings=None) -> str:
    settings = settings or get_settings()
    if settings.llm_api_key.strip():
        return settings.llm_api_key.strip()
    return _first_csv_key(settings.llm_api_keys)


def _resolve_llm_base_url(settings=None) -> str:
    settings = settings or get_settings()
    return (settings.llm_base_url.strip() or OPENROUTER_BASE_URL).rstrip("/")


def _resolve_embedding_api_key(
    api_key: Optional[str] = None,
    *,
    settings=None,
) -> tuple[str, str]:
    settings = settings or get_settings()

    candidates = [
        ("param", api_key or ""),
        ("settings.embedding_api_key", settings.embedding_api_key.strip()),
        ("settings.llm_api_key", settings.llm_api_key.strip()),
        ("settings.llm_api_keys[0]", _first_csv_key(settings.llm_api_keys)),
    ]

    for source, value in candidates:
        if value:
            return value, source

    return "", "unconfigured"


def _ensure_llm_init() -> None:
    global _llm_keys, _llm_index
    if not _llm_keys:
        settings = get_settings()
        _llm_keys = _get_llm_runtime_keys(settings)
        _llm_index = 0


def reset_llm_key_index() -> None:
    global _llm_index
    _ensure_llm_init()
    _llm_index = 0


def get_llm_keys_count() -> int:
    _ensure_llm_init()
    return len(_llm_keys)


def switch_to_next_llm_key() -> bool:
    global _llm_index
    _ensure_llm_init()
    _llm_index += 1
    return _llm_index < len(_llm_keys)


def get_current_llm_api_key() -> Optional[str]:
    _ensure_llm_init()
    if not _llm_keys or _llm_index >= len(_llm_keys):
        return None
    return _llm_keys[_llm_index]


def get_llm_client(api_key: Optional[str] = None) -> OpenAI:
    settings = get_settings()
    resolved_api_key = api_key or get_current_llm_api_key() or _first_configured_llm_key(settings)

    if not resolved_api_key:
        raise RuntimeError("No LLM API key configured")

    return OpenAI(
        base_url=_resolve_llm_base_url(settings),
        api_key=resolved_api_key,
    )


def get_default_llm_model_name() -> str:
    settings = get_settings()
    return settings.llm_model or "gemini-2.5-flash"


def _mask_key(value: Optional[str]) -> str:
    if not value:
        return "<EMPTY>"
    if len(value) > 12:
        return f"{value[:4]}...{value[-4:]}"
    return value


def _provider_name_from_base_url(base_url: str) -> str:
    hostname = (urlparse(base_url).hostname or "").lower()
    if "openrouter" in hostname:
        return "openrouter"
    if hostname:
        return hostname
    return "openai-compatible"


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _is_retryable_provider_error(
    *,
    http_status: Optional[int],
    upstream_code: Optional[Any],
    upstream_message: Optional[str],
) -> bool:
    message = (upstream_message or "").lower()
    numeric_code = _safe_int(upstream_code)

    if "no successful provider responses" in message:
        return True

    if "no endpoints found" in message:
        return True

    if http_status == 404:
        return True

    if numeric_code == 404:
        return True

    if http_status in _RETRYABLE_STATUS_CODES:
        return True

    if numeric_code in _RETRYABLE_STATUS_CODES:
        return True

    return False


class OpenAIEmbeddings:
    """OpenAI-compatible embeddings wrapper with raw response validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        settings = get_settings()
        effective_api_key, api_key_source = _resolve_embedding_api_key(api_key, settings=settings)
        self.base_url = (base_url or settings.embedding_base_url or OPENROUTER_BASE_URL).rstrip("/")
        self.model_name = model_name or settings.embedding_model or "google/gemini-embedding-001"
        self.provider_name = _provider_name_from_base_url(self.base_url)

        logger.info(
            "[Embeddings] Initializing OpenAIEmbeddings - source=%s, key=%s, base_url=%s, model=%s",
            api_key_source,
            _mask_key(effective_api_key),
            self.base_url,
            self.model_name,
        )

        if not effective_api_key:
            raise RuntimeError("No embedding API key configured")

        self.api_key = effective_api_key
        self.client = OpenAI(
            api_key=effective_api_key,
            base_url=self.base_url,
        )

    def _embedding_endpoint(self) -> str:
        return f"{self.base_url}/embeddings"

    def _raise_upstream_error(
        self,
        *,
        message: str,
        retryable: bool,
        http_status: Optional[int] = None,
        upstream_code: Optional[Any] = None,
        upstream_message: Optional[str] = None,
        raw_preview: Optional[str] = None,
        code: str = "EMBEDDING_UPSTREAM_FAILED",
    ) -> None:
        raise EmbeddingProviderError(
            code=code,
            message=message,
            retryable=retryable,
            provider=self.provider_name,
            model=self.model_name,
            base_url=self.base_url,
            http_status=http_status,
            upstream_code=upstream_code,
            upstream_message=upstream_message,
            raw_preview=raw_preview,
        )

    def _post_embeddings(self, input_value: Any, expected_count: int) -> List[List[float]]:
        payload = {
            "model": self.model_name,
            "input": input_value,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self._embedding_endpoint(),
                json=payload,
                headers=headers,
                timeout=EMBEDDING_TIMEOUT_SECONDS,
            )
        except requests.RequestException as err:
            self._raise_upstream_error(
                message=f"Embedding request failed: {err}",
                retryable=True,
                upstream_message=str(err),
            )

        raw_preview = response.text

        try:
            response_payload = response.json()
        except ValueError:
            retryable = response.status_code in _RETRYABLE_STATUS_CODES or response.status_code >= 500
            error_message = f"Embedding provider returned non-JSON response (HTTP {response.status_code})"
            self._raise_upstream_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message=error_message,
                retryable=retryable,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        error_payload = response_payload.get("error") if isinstance(response_payload, dict) else None
        upstream_code = None
        upstream_message = None
        if isinstance(error_payload, dict):
            upstream_code = error_payload.get("code")
            upstream_message = error_payload.get("message") or response.reason
        elif response.status_code >= 400:
            upstream_message = response.reason

        if error_payload or response.status_code >= 400:
            retryable = _is_retryable_provider_error(
                http_status=response.status_code,
                upstream_code=upstream_code,
                upstream_message=upstream_message,
            )
            message = upstream_message or f"Embedding upstream failed with HTTP {response.status_code}"
            self._raise_upstream_error(
                message=f"Embedding upstream failed: {message}",
                retryable=retryable,
                http_status=response.status_code,
                upstream_code=upstream_code,
                upstream_message=upstream_message,
                raw_preview=raw_preview,
            )

        if not isinstance(response_payload, dict):
            self._raise_upstream_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message="Embedding provider returned a malformed JSON payload",
                retryable=True,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        data = response_payload.get("data")
        if not isinstance(data, list) or not data:
            self._raise_upstream_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message="Embedding provider returned no embedding data",
                retryable=True,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        sorted_data = sorted(
            data,
            key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
        )

        embeddings: List[List[float]] = []
        for item in sorted_data:
            if not isinstance(item, dict):
                self._raise_upstream_error(
                    code="EMBEDDING_RESPONSE_INVALID",
                    message="Embedding response item had an unexpected shape",
                    retryable=True,
                    http_status=response.status_code,
                    raw_preview=raw_preview,
                )

            embedding = item.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                self._raise_upstream_error(
                    code="EMBEDDING_RESPONSE_INVALID",
                    message="Embedding response item did not include a valid vector",
                    retryable=True,
                    http_status=response.status_code,
                    raw_preview=raw_preview,
                )

            embeddings.append(embedding)

        if len(embeddings) != expected_count:
            self._raise_upstream_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message=f"Embedding response count mismatch: expected {expected_count}, got {len(embeddings)}",
                retryable=True,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        response = self._post_embeddings(text, expected_count=1)
        return response[0]

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_query, text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._post_embeddings(texts, expected_count=len(texts))

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)


def create_embedding_model(
    api_key: Optional[str] = None,
    *,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
    )


def get_embedding_model() -> Optional[OpenAIEmbeddings]:
    effective_api_key, _ = _resolve_embedding_api_key()
    if not effective_api_key:
        return None
    return create_embedding_model()


def get_fallback_embedding_model() -> Optional[OpenAIEmbeddings]:
    settings = get_settings()
    effective_api_key, _ = _resolve_embedding_api_key(settings=settings)
    if not effective_api_key or not settings.embedding_fallback_model:
        return None
    return create_embedding_model(
        model_name=settings.embedding_fallback_model,
        base_url=settings.embedding_base_url,
    )


def get_query_entity_extraction_model() -> Optional[ChatGoogleGenerativeAI]:
    _ensure_llm_init()
    if not _llm_keys:
        return None

    api_key = _llm_keys[0]
    schema = {
        "title": "extract_entities_schema",
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["entities"],
    }
    return ChatGoogleGenerativeAI(
        model=get_settings().llm_model or "gemini-2.5-flash",
        api_key=api_key,
    ).with_structured_output(schema)


def get_graph_extraction_model() -> Optional[ChatGoogleGenerativeAI]:
    _ensure_llm_init()
    if not _llm_keys or _llm_index >= len(_llm_keys):
        return None

    api_key = _llm_keys[_llm_index]
    schema = {
        "title": "graph_extraction_schema",
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
                    "required": ["name", "type"],
                },
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["source", "target", "type"],
                },
            },
        },
        "required": ["entities", "relationships"],
    }
    return ChatGoogleGenerativeAI(
        model=get_settings().llm_model or "gemini-2.5-flash",
        api_key=api_key,
    ).with_structured_output(schema)


def get_answer_generation_model(schema, options=None, api_key: Optional[str] = None) -> Optional[ChatGoogleGenerativeAI]:
    _ensure_llm_init()

    if api_key is None:
        if not _llm_keys or _llm_index >= len(_llm_keys):
            return None
        api_key = _llm_keys[_llm_index]

    temperature = (options or {}).get("temperature", 0.7)
    thinking_budget = (options or {}).get("thinking_budget", 0)
    model_kwargs = {
        "thinking_config": {
            "thinking_budget": thinking_budget
        }
    }

    base = ChatGoogleGenerativeAI(
        model=get_settings().llm_model or "gemini-2.5-flash",
        api_key=api_key,
        temperature=temperature,
        model_kwargs=model_kwargs,
    )
    logger.debug("Created answer generation model: %s", base)
    return base.with_structured_output(schema)


def _build_retry_error_message(
    operation_name: str,
    key_count: int,
    attempts_made: int,
    last_error: Optional[Exception],
) -> str:
    if key_count == 0:
        error_msg = f"No API keys configured for {operation_name}"
    else:
        error_msg = (
            f"All API keys failed for {operation_name} "
            f"(attempted {attempts_made}/{key_count} configured keys)"
        )

    if last_error is not None:
        error_msg += f": {str(last_error)}"

    return error_msg


async def with_llm_retry_async(
    operation_name: str,
    operation_func: Callable,
    *args,
    max_retries: Optional[int] = None,
    error_type: Type[Exception] = RuntimeError,
    retry_delay: float = 0.5,
    **kwargs,
) -> Any:
    reset_llm_key_index()
    last_error: Optional[Exception] = None
    key_count = get_llm_keys_count()
    max_attempts = max_retries if max_retries is not None else (key_count or 10)
    attempts_made = 0

    for attempt in range(max_attempts):
        api_key = get_current_llm_api_key()
        if not api_key:
            break

        attempts_made += 1

        try:
            return await operation_func(api_key, *args, **kwargs)
        except Exception as err:
            logger.warning("[%s] attempt %s/%s failed: %s", operation_name, attempt + 1, max_attempts, err)
            last_error = err
            if not switch_to_next_llm_key():
                break
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)

    error_msg = _build_retry_error_message(operation_name, key_count, attempts_made, last_error)

    if error_type == HTTPException:
        raise HTTPException(status_code=500, detail=error_msg)
    raise error_type(error_msg)


def with_llm_retry_sync(
    operation_name: str,
    operation_func: Callable,
    *args,
    max_retries: Optional[int] = None,
    error_type: Type[Exception] = RuntimeError,
    retry_delay: float = 0.5,
    **kwargs,
) -> Any:
    reset_llm_key_index()
    last_error: Optional[Exception] = None
    key_count = get_llm_keys_count()
    max_attempts = max_retries if max_retries is not None else (key_count or 10)
    attempts_made = 0

    for attempt in range(max_attempts):
        api_key = get_current_llm_api_key()
        if not api_key:
            break

        attempts_made += 1

        try:
            return operation_func(api_key, *args, **kwargs)
        except Exception as err:
            logger.warning("[%s] attempt %s/%s failed: %s", operation_name, attempt + 1, max_attempts, err)
            last_error = err
            if not switch_to_next_llm_key():
                break
            if retry_delay > 0:
                time.sleep(retry_delay)

    error_msg = _build_retry_error_message(operation_name, key_count, attempts_made, last_error)

    if error_type == HTTPException:
        raise HTTPException(status_code=500, detail=error_msg)
    raise error_type(error_msg)
