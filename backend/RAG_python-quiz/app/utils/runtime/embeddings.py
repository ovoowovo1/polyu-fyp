from __future__ import annotations

import asyncio
import base64
from typing import Any, List, Optional
from urllib.parse import urlparse

import requests

from app.utils.ingest_errors import EmbeddingProviderError
from app.utils.runtime import embedding_provider_response
from app.utils.runtime.llm_client import OPENROUTER_BASE_URL
from app.utils.runtime.llm_keys import first_csv_key

EMBEDDING_TIMEOUT_SECONDS = 120


def image_bytes_to_data_url(content: bytes, mime_type: str) -> str:
    normalized_mime = (mime_type or "application/octet-stream").lower()
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{normalized_mime};base64,{encoded}"


def image_embedding_input(content: bytes, mime_type: str) -> dict[str, list[dict[str, dict[str, str] | str]]]:
    return {
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": image_bytes_to_data_url(content, mime_type)},
            }
        ]
    }


def mask_key(value: Optional[str]) -> str:
    if not value:
        return "<EMPTY>"
    if len(value) > 12:
        return f"{value[:4]}...{value[-4:]}"
    return value


def provider_name_from_base_url(base_url: str) -> str:
    hostname = (urlparse(base_url).hostname or "").lower()
    if "openrouter" in hostname:
        return "openrouter"
    if hostname:
        return hostname
    return "openai-compatible"


def resolve_embedding_api_key(
    api_key: Optional[str] = None,
    *,
    settings,
) -> tuple[str, str]:
    candidates = [
        ("param", api_key or ""),
        ("settings.embedding_api_key", settings.embedding_api_key.strip()),
        ("settings.llm_api_key", settings.llm_api_key.strip()),
        ("settings.llm_api_keys[0]", first_csv_key(settings.llm_api_keys)),
    ]

    for source, value in candidates:
        if value:
            return value, source

    return "", "unconfigured"


class OpenAIEmbeddings:
    """OpenAI-compatible embeddings wrapper with raw response validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        settings,
        openai_cls,
        post_func=requests.post,
        logger,
    ):
        effective_api_key, api_key_source = resolve_embedding_api_key(api_key, settings=settings)
        self.base_url = (base_url or settings.embedding_base_url or OPENROUTER_BASE_URL).rstrip("/")
        self.model_name = model_name or settings.embedding_model or "google/gemini-embedding-2-preview"
        self.provider_name = provider_name_from_base_url(self.base_url)
        self._post_func = post_func

        logger.info(
            "[Embeddings] Initializing OpenAIEmbeddings - source=%s, key=%s, base_url=%s, model=%s",
            api_key_source,
            mask_key(effective_api_key),
            self.base_url,
            self.model_name,
        )

        if not effective_api_key:
            raise RuntimeError("No embedding API key configured")

        self.api_key = effective_api_key
        self.client = openai_cls(
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
        payload, headers = embedding_provider_response.build_embedding_request(
            self.api_key,
            self.model_name,
            input_value,
        )
        response = embedding_provider_response.post_embedding_request(
            post_func=self._post_func,
            endpoint=self._embedding_endpoint(),
            payload=payload,
            headers=headers,
            timeout=EMBEDDING_TIMEOUT_SECONDS,
            raise_error=self._raise_upstream_error,
        )

        raw_preview = response.text
        response_payload = embedding_provider_response.parse_embedding_response_json(
            response,
            raw_preview,
            self._raise_upstream_error,
        )
        embedding_provider_response.maybe_raise_upstream_error(
            response,
            response_payload,
            raw_preview,
            self._raise_upstream_error,
        )
        data = embedding_provider_response.validate_embedding_response_data(
            response,
            response_payload,
            raw_preview,
            self._raise_upstream_error,
        )
        return embedding_provider_response.collect_embeddings(
            response,
            data,
            expected_count,
            raw_preview,
            self._raise_upstream_error,
        )

    def embed_query(self, text: str) -> List[float]:
        response = self._post_embeddings(text, expected_count=1)
        return response[0]

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_query, text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._post_embeddings(texts, expected_count=len(texts))

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)

    def embed_images(self, images: List[dict[str, Any]]) -> List[List[float]]:
        inputs = [
            image_embedding_input(
                image["content"],
                image.get("mime_type") or image.get("mimetype") or "application/octet-stream",
            )
            for image in images
        ]
        return self._post_embeddings(inputs, expected_count=len(inputs))

    async def aembed_images(self, images: List[dict[str, Any]]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_images, images)
