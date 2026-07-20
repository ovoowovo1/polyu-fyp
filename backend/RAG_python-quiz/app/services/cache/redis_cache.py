from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

import httpx
from fastapi import Response

from app.config import get_settings
from app.logger import get_logger


logger = get_logger(__name__)

CACHE_SCHEMA_VERSION = "v2"
CACHE_KEY_PREFIX = "polyu"
REQUEST_TIMEOUT_SECONDS = 2
HEADER_CACHE_STATUS = "X-Redis-Cache"
HEADER_CACHE_SCOPE = "X-Redis-Cache-Scope"
CACHE_HIT = "HIT"
CACHE_MISS = "MISS"
CACHE_BYPASS = "BYPASS"
CACHE_ERROR = "ERROR"

_client: httpx.AsyncClient | None = None


@dataclass(frozen=True)
class CacheResult:
    value: dict[str, Any]
    status: str
    scope: str


async def get_or_set_json(
    scope: str,
    params: dict[str, Any],
    loader: Callable[[], Awaitable[dict[str, Any]]],
    *,
    version_namespaces: Sequence[str] = (),
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    result = await get_or_set_json_with_status(
        scope,
        params,
        loader,
        version_namespaces=version_namespaces,
        ttl_seconds=ttl_seconds,
    )
    return result.value


async def get_or_set_json_with_status(
    scope: str,
    params: dict[str, Any],
    loader: Callable[[], Awaitable[dict[str, Any]]],
    *,
    version_namespaces: Sequence[str] = (),
    ttl_seconds: int | None = None,
) -> CacheResult:
    settings = get_settings()
    if not _is_enabled(settings):
        return await load_without_cache(scope, loader, reason="disabled")

    versions = {
        namespace: version
        for namespace, version in zip(
            version_namespaces,
            await _get_versions(version_namespaces),
        )
    }
    key = build_cache_key(scope, params, versions=versions)
    cached, get_error = await get_json_with_error(key)
    if get_error:
        _log_cache(CACHE_ERROR, scope, reason=get_error)
        return CacheResult(await loader(), CACHE_ERROR, scope)
    if cached is not None:
        _log_cache(CACHE_HIT, scope)
        return CacheResult(cached, CACHE_HIT, scope)

    value = await loader()
    ttl = ttl_seconds if ttl_seconds is not None else settings.redis_cache_ttl_seconds
    if await set_json(key, value, ttl_seconds=ttl):
        _log_cache(CACHE_MISS, scope)
        _log_cache("SET", scope)
        return CacheResult(value, CACHE_MISS, scope)

    _log_cache(CACHE_ERROR, scope, reason="set_failed")
    return CacheResult(value, CACHE_ERROR, scope)


async def load_without_cache(
    scope: str,
    loader: Callable[[], Awaitable[dict[str, Any]]],
    *,
    reason: str,
) -> CacheResult:
    _log_cache(CACHE_BYPASS, scope, reason=reason)
    return CacheResult(await loader(), CACHE_BYPASS, scope)


def set_response_cache_headers(response: Response, result: CacheResult) -> None:
    response.headers[HEADER_CACHE_STATUS] = result.status
    response.headers[HEADER_CACHE_SCOPE] = result.scope


async def invalidate_namespaces(*namespaces: str) -> None:
    for namespace in sorted({namespace for namespace in namespaces if namespace}):
        await _execute(["INCR", _version_key(namespace)])


def is_enabled() -> bool:
    return _is_enabled(get_settings())


async def get_version(namespace: str) -> str:
    result = await _execute(["GET", _version_key(namespace)])
    return str(result or "0")


async def get_json(key: str) -> dict[str, Any] | None:
    value, _error = await get_json_with_error(key)
    return value


async def get_json_with_error(key: str) -> tuple[dict[str, Any] | None, str | None]:
    command_result = await _execute_command(["GET", key])
    if not command_result.ok:
        return None, command_result.error or "get_failed"

    result = command_result.result
    if not isinstance(result, str) or not result:
        return None, None

    try:
        value = json.loads(result)
    except json.JSONDecodeError as error:
        logger.warning("Redis cache payload is not valid JSON for key=%s: %s", key, error)
        return None, "invalid_json"

    if not isinstance(value, dict):
        return None, "invalid_payload"

    return value, None


async def set_json(key: str, value: dict[str, Any], *, ttl_seconds: int) -> bool:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (await _execute_command(["SET", key, payload, "EX", max(1, int(ttl_seconds))])).ok


def build_cache_key(
    scope: str,
    params: dict[str, Any],
    *,
    versions: dict[str, str] | None = None,
) -> str:
    canonical = json.dumps(
        {"params": params, "versions": versions or {}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{CACHE_SCHEMA_VERSION}:cache:{scope}:{digest}"


def _version_key(namespace: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{CACHE_SCHEMA_VERSION}:version:{namespace}"


async def _execute(command: list[Any]) -> Any:
    result = await _execute_command(command)
    return result.result if result.ok else None


@dataclass(frozen=True)
class _RedisCommandResult:
    ok: bool
    result: Any = None
    error: str | None = None


async def initialize_client(settings=None) -> None:
    global _client

    settings = settings or get_settings()
    if not _is_enabled(settings):
        return
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)


async def close_client() -> None:
    global _client

    client = _client
    _client = None
    if client is not None and not client.is_closed:
        await client.aclose()


async def _get_client() -> httpx.AsyncClient | None:
    await initialize_client()
    return _client


async def _get_versions(namespaces: Sequence[str]) -> list[str]:
    return [await get_version(namespace) for namespace in namespaces]


async def _execute_command(command: list[Any]) -> _RedisCommandResult:
    settings = get_settings()
    if not _is_enabled(settings):
        return _RedisCommandResult(ok=False, error="disabled")

    client = await _get_client()
    if client is None:
        return _RedisCommandResult(ok=False, error="disabled")

    try:
        response = await client.post(
            settings.upstash_redis_rest_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
                "Content-Type": "application/json",
            },
            json=command,
        )
        if response.status_code != 200:
            logger.warning("Redis cache command failed status=%s body=%s", response.status_code, response.text)
            return _RedisCommandResult(ok=False, error=f"http_{response.status_code}")

        payload = response.json()
    except Exception as error:  # pragma: no cover - defensive fallback for network/client errors
        logger.warning("Redis cache command failed: %s", error)
        return _RedisCommandResult(ok=False, error=str(error))

    if payload.get("error"):
        logger.warning("Redis cache command returned error: %s", payload["error"])
        return _RedisCommandResult(ok=False, error=str(payload["error"]))

    return _RedisCommandResult(ok=True, result=payload.get("result"))


def _is_enabled(settings) -> bool:
    return bool(
        getattr(settings, "redis_cache_enabled", False)
        and getattr(settings, "upstash_redis_rest_url", "")
        and getattr(settings, "upstash_redis_rest_token", "")
    )


def _log_cache(status: str, scope: str, *, reason: str | None = None) -> None:
    message = "Redis cache %s scope=%s"
    if reason:
        logger.info(message + " reason=%s", status, scope, reason)
    else:
        logger.info(message, status, scope)
