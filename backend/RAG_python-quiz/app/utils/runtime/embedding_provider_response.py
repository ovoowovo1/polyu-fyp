from __future__ import annotations

from typing import Any, Callable, List, Optional

import requests

from app.utils.runtime.retry import RETRYABLE_STATUS_CODES, is_retryable_provider_error

RaiseEmbeddingError = Callable[..., None]


def build_embedding_request(api_key: str, model_name: str, input_value: Any) -> tuple[dict, dict]:
    return (
        {
            "model": model_name,
            "input": input_value,
            "encoding_format": "float",
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )


def post_embedding_request(
    *,
    post_func,
    endpoint: str,
    payload: dict,
    headers: dict,
    timeout: int,
    raise_error: RaiseEmbeddingError,
):
    try:
        return post_func(
            endpoint,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as err:
        raise_error(
            message=f"Embedding request failed: {err}",
            retryable=True,
            upstream_message=str(err),
        )


def parse_embedding_response_json(response, raw_preview: str, raise_error: RaiseEmbeddingError):
    try:
        return response.json()
    except ValueError:
        retryable = response.status_code in RETRYABLE_STATUS_CODES or response.status_code >= 500
        raise_error(
            code="EMBEDDING_RESPONSE_INVALID",
            message=f"Embedding provider returned non-JSON response (HTTP {response.status_code})",
            retryable=retryable,
            http_status=response.status_code,
            raw_preview=raw_preview,
        )


def upstream_error_details(response, response_payload: Any) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
    error_payload = response_payload.get("error") if isinstance(response_payload, dict) else None
    upstream_code = None
    upstream_message = None
    if isinstance(error_payload, dict):
        upstream_code = error_payload.get("code")
        upstream_message = error_payload.get("message") or response.reason
    elif response.status_code >= 400:
        upstream_message = response.reason
    return error_payload, upstream_code, upstream_message


def maybe_raise_upstream_error(
    response,
    response_payload: Any,
    raw_preview: str,
    raise_error: RaiseEmbeddingError,
) -> None:
    error_payload, upstream_code, upstream_message = upstream_error_details(response, response_payload)
    if error_payload or response.status_code >= 400:
        retryable = is_retryable_provider_error(
            http_status=response.status_code,
            upstream_code=upstream_code,
            upstream_message=upstream_message,
        )
        message = upstream_message or f"Embedding upstream failed with HTTP {response.status_code}"
        raise_error(
            message=f"Embedding upstream failed: {message}",
            retryable=retryable,
            http_status=response.status_code,
            upstream_code=upstream_code,
            upstream_message=upstream_message,
            raw_preview=raw_preview,
        )


def validate_embedding_response_data(
    response,
    response_payload: Any,
    raw_preview: str,
    raise_error: RaiseEmbeddingError,
) -> list:
    if not isinstance(response_payload, dict):
        raise_error(
            code="EMBEDDING_RESPONSE_INVALID",
            message="Embedding provider returned a malformed JSON payload",
            retryable=True,
            http_status=response.status_code,
            raw_preview=raw_preview,
        )

    data = response_payload.get("data")
    if not isinstance(data, list) or not data:
        raise_error(
            code="EMBEDDING_RESPONSE_INVALID",
            message="Embedding provider returned no embedding data",
            retryable=True,
            http_status=response.status_code,
            raw_preview=raw_preview,
        )
    return data


def collect_embeddings(
    response,
    data: list,
    expected_count: int,
    raw_preview: str,
    raise_error: RaiseEmbeddingError,
) -> List[List[float]]:
    sorted_data = sorted(
        data,
        key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
    )

    embeddings: List[List[float]] = []
    for item in sorted_data:
        if not isinstance(item, dict):
            raise_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message="Embedding response item had an unexpected shape",
                retryable=True,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        embedding = item.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise_error(
                code="EMBEDDING_RESPONSE_INVALID",
                message="Embedding response item did not include a valid vector",
                retryable=True,
                http_status=response.status_code,
                raw_preview=raw_preview,
            )

        embeddings.append(embedding)

    if len(embeddings) != expected_count:
        raise_error(
            code="EMBEDDING_RESPONSE_INVALID",
            message=f"Embedding response count mismatch: expected {expected_count}, got {len(embeddings)}",
            retryable=True,
            http_status=response.status_code,
            raw_preview=raw_preview,
        )

    return embeddings
