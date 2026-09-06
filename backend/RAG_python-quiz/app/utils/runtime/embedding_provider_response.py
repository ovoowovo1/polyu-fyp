from __future__ import annotations

from typing import Any, Callable, List, Optional

import math

import requests

from app.utils.runtime.retry import RETRYABLE_STATUS_CODES, is_retryable_provider_error

RaiseEmbeddingError = Callable[..., None]


def build_embedding_request(api_key: str, model_name: str, input_value: Any) -> tuple[dict, dict]:
    values = [input_value] if isinstance(input_value, str) else input_value
    if not isinstance(values, list) or not values:
        raise ValueError("Embedding input must be a non-empty batch")
    text_batch = all(isinstance(value, str) and value.strip() for value in values)
    image_batch = all(isinstance(value, dict) and isinstance(value.get("content"), list)
                      and value["content"] for value in values)
    if not text_batch and not image_batch:
        raise ValueError("Embedding batches must contain only strings or only multimodal objects")
    if image_batch:
        for value in values:
            for part in value["content"]:
                if not isinstance(part, dict) or part.get("type") != "image_url" or not isinstance(part.get("image_url"), dict) or not isinstance(part["image_url"].get("url"), str) or not part["image_url"]["url"]:
                    raise ValueError("Image embedding input must provide an image_url")
    return (
        {
            "model": model_name,
            "input": input_value,
            "encoding_format": "float",
            "dimensions": 3072,
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
            retryable=False,
            http_status=response.status_code,
            raw_preview=raw_preview,
        )

    data = response_payload.get("data")
    if not isinstance(data, list) or not data:
        raise_error(
            code="EMBEDDING_RESPONSE_INVALID",
            message="Embedding provider returned no embedding data",
            retryable=False,
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
    indices = [item.get("index") if isinstance(item, dict) else None for item in data]
    if (len(data) != expected_count or any(type(index) is not int for index in indices)
            or set(indices) != set(range(expected_count))):
        raise_error(code="EMBEDDING_RESPONSE_INVALID", message="Embedding response indices/count do not match the requested chunks",
                    retryable=False, http_status=response.status_code, raw_preview=raw_preview)
    embeddings = []
    for item in sorted(data, key=lambda entry: entry["index"]):
        vector = item.get("embedding")
        if (not isinstance(vector, list) or len(vector) != 3072
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)):
            raise_error(code="EMBEDDING_RESPONSE_INVALID", message="Embedding response must contain 3072 finite numeric values per chunk",
                        retryable=False, http_status=response.status_code, raw_preview=raw_preview)
        embeddings.append(vector)
    return embeddings
