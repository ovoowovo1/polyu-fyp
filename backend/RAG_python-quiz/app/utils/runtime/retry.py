from __future__ import annotations

from typing import Any, Callable, Optional, Type

from fastapi import HTTPException

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def is_retryable_provider_error(
    *,
    http_status: Optional[int],
    upstream_code: Optional[Any],
    upstream_message: Optional[str],
) -> bool:
    message = (upstream_message or "").lower()
    numeric_code = safe_int(upstream_code)

    if "no successful provider responses" in message:
        return True
    if "no endpoints found" in message:
        return True
    if http_status == 404:
        return True
    if numeric_code == 404:
        return True
    if http_status in RETRYABLE_STATUS_CODES:
        return True
    if numeric_code in RETRYABLE_STATUS_CODES:
        return True
    return False


def build_retry_error_message(
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
    reset_key_index_func,
    key_count_func,
    current_key_func,
    switch_key_func,
    sleep_func,
    logger,
    **kwargs,
) -> Any:
    reset_key_index_func()
    last_error: Optional[Exception] = None
    key_count = key_count_func()
    max_attempts = max_retries if max_retries is not None else (key_count or 10)
    attempts_made = 0

    for attempt in range(max_attempts):
        api_key = current_key_func()
        if not api_key:
            break

        attempts_made += 1

        try:
            return await operation_func(api_key, *args, **kwargs)
        except Exception as err:
            logger.warning("[%s] attempt %s/%s failed: %s", operation_name, attempt + 1, max_attempts, err)
            last_error = err
            if not switch_key_func():
                break
            if retry_delay > 0:
                await sleep_func(retry_delay)

    error_msg = build_retry_error_message(operation_name, key_count, attempts_made, last_error)

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
    reset_key_index_func,
    key_count_func,
    current_key_func,
    switch_key_func,
    sleep_func,
    logger,
    **kwargs,
) -> Any:
    reset_key_index_func()
    last_error: Optional[Exception] = None
    key_count = key_count_func()
    max_attempts = max_retries if max_retries is not None else (key_count or 10)
    attempts_made = 0

    for attempt in range(max_attempts):
        api_key = current_key_func()
        if not api_key:
            break

        attempts_made += 1

        try:
            return operation_func(api_key, *args, **kwargs)
        except Exception as err:
            logger.warning("[%s] attempt %s/%s failed: %s", operation_name, attempt + 1, max_attempts, err)
            last_error = err
            if not switch_key_func():
                break
            if retry_delay > 0:
                sleep_func(retry_delay)

    error_msg = build_retry_error_message(operation_name, key_count, attempts_made, last_error)

    if error_type == HTTPException:
        raise HTTPException(status_code=500, detail=error_msg)
    raise error_type(error_msg)
