import asyncio
from typing import Any, Callable

from fastapi import HTTPException

from app.services.core.exceptions import ServiceError


ErrorPredicate = Callable[[Exception], bool]


def error_detail(
    message: str,
    *,
    details: Any = None,
    code: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message}
    if details is not None:
        payload["details"] = details
    if code is not None:
        payload["code"] = code
    payload.update(extra)
    return payload


def success_payload(
    message: str,
    data: Any = None,
    *,
    include_data: bool = True,
    include_root_fields: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if include_data:
        payload["data"] = data
    if include_root_fields and isinstance(data, dict):
        payload.update(data)
    payload.update(extra)
    return payload


def exception_is(*types: type[BaseException]) -> ErrorPredicate:
    return lambda error: isinstance(error, types)


def require_teacher(user: dict[str, Any], detail: str, teacher_checker: Callable[[str], bool]) -> None:
    if not teacher_checker(user["user_id"]):
        raise HTTPException(status_code=403, detail=detail)


def require_allowed(allowed: bool, detail: str = "Permission denied") -> None:
    if not allowed:
        raise HTTPException(status_code=403, detail=detail)


def service_error_to_http(error: ServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _raise_mapped_error(
    error: Exception,
    *,
    error_rules: list[tuple[ErrorPredicate, int, Any]] | None,
    fallback_status: int,
    fallback_detail: Any,
    logger,
    log_message: str | None,
) -> None:
    for predicate, status_code, detail in error_rules or []:
        if predicate(error):
            resolved_detail = detail(error) if callable(detail) else detail
            raise HTTPException(status_code=status_code, detail=resolved_detail) from error

    if logger and log_message:
        logger.error(log_message, error, exc_info=(fallback_status >= 500))
    resolved_detail = fallback_detail(error) if callable(fallback_detail) else fallback_detail
    raise HTTPException(status_code=fallback_status, detail=resolved_detail) from error


async def run_service(
    func: Callable[..., Any],
    *args: Any,
    error_rules: list[tuple[ErrorPredicate, int, Any]] | None = None,
    fallback_status: int = 500,
    fallback_detail: Any = "Internal server error",
    logger=None,
    log_message: str | None = None,
) -> Any:
    return await _run_with_error_mapping(
        lambda: asyncio.to_thread(func, *args), error_rules, fallback_status, fallback_detail, logger, log_message
    )


async def run_async_service(
    func: Callable[..., Any],
    *args: Any,
    error_rules: list[tuple[ErrorPredicate, int, Any]] | None = None,
    fallback_status: int = 500,
    fallback_detail: Any = "Internal server error",
    logger=None,
    log_message: str | None = None,
    **kwargs: Any,
) -> Any:
    return await _run_with_error_mapping(
        lambda: func(*args, **kwargs), error_rules, fallback_status, fallback_detail, logger, log_message
    )


async def _run_with_error_mapping(call, error_rules, fallback_status, fallback_detail, logger, log_message):
    try:
        return await call()
    except HTTPException:
        raise
    except ServiceError as error:
        raise service_error_to_http(error) from error
    except Exception as error:
        _raise_mapped_error(
            error,
            error_rules=error_rules,
            fallback_status=fallback_status,
            fallback_detail=fallback_detail,
            logger=logger,
            log_message=log_message,
        )
