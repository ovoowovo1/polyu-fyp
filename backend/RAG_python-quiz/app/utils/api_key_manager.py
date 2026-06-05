# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, List, Optional, Type

import requests
from fastapi import HTTPException
from openai import OpenAI

from app.config import get_settings
from app.logger import get_logger
from app.utils.runtime import embeddings as embedding_runtime
from app.utils.runtime import llm_client, llm_keys, retry

logger = get_logger(__name__)

OPENROUTER_BASE_URL = llm_client.OPENROUTER_BASE_URL
EMBEDDING_TIMEOUT_SECONDS = embedding_runtime.EMBEDDING_TIMEOUT_SECONDS
_RETRYABLE_STATUS_CODES = retry.RETRYABLE_STATUS_CODES

_llm_keys: List[str] = []
_llm_index = 0


def _split_api_keys(raw_value: str) -> List[str]:
    return llm_keys.split_api_keys(raw_value)


def _first_csv_key(raw_value: str) -> str:
    return llm_keys.first_csv_key(raw_value)


def _get_llm_runtime_keys(settings=None) -> List[str]:
    return llm_keys.get_llm_runtime_keys(settings or get_settings())


def _first_configured_llm_key(settings=None) -> str:
    return llm_keys.first_configured_llm_key(settings or get_settings())


def _resolve_llm_base_url(settings=None) -> str:
    return llm_client.resolve_llm_base_url(settings or get_settings())


def _resolve_embedding_api_key(
    api_key: Optional[str] = None,
    *,
    settings=None,
) -> tuple[str, str]:
    return embedding_runtime.resolve_embedding_api_key(api_key, settings=settings or get_settings())


def _ensure_llm_init() -> None:
    global _llm_keys, _llm_index
    _llm_keys, _llm_index = llm_keys.ensure_llm_init(_llm_keys, _llm_index, get_settings())


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
    return llm_keys.current_llm_api_key(_llm_keys, _llm_index)


def get_llm_client(api_key: Optional[str] = None) -> OpenAI:
    settings = get_settings()
    resolved_api_key = api_key or get_current_llm_api_key() or _first_configured_llm_key(settings)
    return llm_client.create_llm_client(
        api_key=resolved_api_key,
        settings=settings,
        openai_cls=OpenAI,
    )


def get_default_llm_model_name() -> str:
    return llm_client.default_llm_model_name(get_settings())


def _mask_key(value: Optional[str]) -> str:
    return embedding_runtime.mask_key(value)


def _provider_name_from_base_url(base_url: str) -> str:
    return embedding_runtime.provider_name_from_base_url(base_url)


def _safe_int(value: Any) -> Optional[int]:
    return retry.safe_int(value)


def _is_retryable_provider_error(
    *,
    http_status: Optional[int],
    upstream_code: Optional[Any],
    upstream_message: Optional[str],
) -> bool:
    return retry.is_retryable_provider_error(
        http_status=http_status,
        upstream_code=upstream_code,
        upstream_message=upstream_message,
    )


class OpenAIEmbeddings(embedding_runtime.OpenAIEmbeddings):
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            settings=get_settings(),
            openai_cls=OpenAI,
            post_func=lambda *args, **kwargs: requests.post(*args, **kwargs),
            logger=logger,
        )


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


def _build_retry_error_message(
    operation_name: str,
    key_count: int,
    attempts_made: int,
    last_error: Optional[Exception],
) -> str:
    return retry.build_retry_error_message(operation_name, key_count, attempts_made, last_error)


async def with_llm_retry_async(
    operation_name: str,
    operation_func: Callable,
    *args,
    max_retries: Optional[int] = None,
    error_type: Type[Exception] = RuntimeError,
    retry_delay: float = 0.5,
    **kwargs,
) -> Any:
    return await retry.with_llm_retry_async(
        operation_name,
        operation_func,
        *args,
        max_retries=max_retries,
        error_type=error_type,
        retry_delay=retry_delay,
        reset_key_index_func=reset_llm_key_index,
        key_count_func=get_llm_keys_count,
        current_key_func=get_current_llm_api_key,
        switch_key_func=switch_to_next_llm_key,
        sleep_func=asyncio.sleep,
        logger=logger,
        **kwargs,
    )


def with_llm_retry_sync(
    operation_name: str,
    operation_func: Callable,
    *args,
    max_retries: Optional[int] = None,
    error_type: Type[Exception] = RuntimeError,
    retry_delay: float = 0.5,
    **kwargs,
) -> Any:
    return retry.with_llm_retry_sync(
        operation_name,
        operation_func,
        *args,
        max_retries=max_retries,
        error_type=error_type,
        retry_delay=retry_delay,
        reset_key_index_func=reset_llm_key_index,
        key_count_func=get_llm_keys_count,
        current_key_func=get_current_llm_api_key,
        switch_key_func=switch_to_next_llm_key,
        sleep_func=time.sleep,
        logger=logger,
        **kwargs,
    )
