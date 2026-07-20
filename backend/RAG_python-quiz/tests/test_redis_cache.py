import asyncio
import json
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from fastapi import Response

from app.services.cache import redis_cache
from tests.support import FakeResponse, make_settings


def enabled_settings(**overrides):
    return make_settings(
        redis_cache_enabled=True,
        upstash_redis_rest_url="https://redis.example",
        upstash_redis_rest_token="token",
        **overrides,
    )


class FakeAsyncClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.is_closed = False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    async def aclose(self):
        self.is_closed = True


@contextmanager
def patched_redis(settings, responses=()):
    client = FakeAsyncClient(responses)
    with patch("app.services.cache.redis_cache.get_settings", return_value=settings), patch.object(
        redis_cache, "_client", client
    ):
        yield client


class RedisCacheTests(unittest.TestCase):
    def test_disabled_cache_loads_without_redis(self):
        loader = AsyncMock(return_value={"value": 1})

        with patch("app.services.cache.redis_cache.get_settings", return_value=make_settings()), patch.object(
            redis_cache, "_client", None
        ):
            result = asyncio.run(redis_cache.get_or_set_json("scope", {"id": "1"}, loader))

        self.assertEqual(result, {"value": 1})
        loader.assert_awaited_once()
        self.assertFalse(redis_cache._is_enabled(make_settings()))

    def test_cache_hit_returns_cached_payload_without_loader(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(),
            [
                FakeResponse(payload={"result": "4"}),
                FakeResponse(payload={"result": json.dumps({"value": "cached"})}),
            ],
        ) as client:
            result = asyncio.run(
                redis_cache.get_or_set_json(
                    "scope", {"id": "1"}, loader, version_namespaces=["items"]
                )
            )

        self.assertEqual(result, {"value": "cached"})
        loader.assert_not_awaited()
        self.assertEqual(len(client.calls), 2)

    def test_cache_hit_result_includes_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(), [FakeResponse(payload={"result": json.dumps({"value": "cached"})})]
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "cached"})
        self.assertEqual(result.status, redis_cache.CACHE_HIT)
        loader.assert_not_awaited()

    def test_cache_miss_loads_and_sets_with_ttl(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(redis_cache_ttl_seconds=0),
            [
                FakeResponse(payload={"result": "0"}),
                FakeResponse(payload={"result": None}),
                FakeResponse(payload={"result": "OK"}),
            ],
        ) as client:
            result = asyncio.run(
                redis_cache.get_or_set_json(
                    "scope", {"id": "1"}, loader, version_namespaces=["items"]
                )
            )

        self.assertEqual(result, {"value": "fresh"})
        loader.assert_awaited_once()
        set_command = client.calls[-1][1]["json"]
        self.assertEqual(set_command[0], "SET")
        self.assertEqual(set_command[-2:], ["EX", 1])

    def test_cache_miss_result_includes_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(),
            [FakeResponse(payload={"result": None}), FakeResponse(payload={"result": "OK"})],
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_MISS)
        loader.assert_awaited_once()

    def test_cache_set_failure_reports_error_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(),
            [FakeResponse(payload={"result": None}), FakeResponse(status_code=500, payload={"error": "bad"}, text="bad")],
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_ERROR)
        loader.assert_awaited_once()

    def test_cache_miss_can_override_ttl(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(),
            [FakeResponse(payload={"result": None}), FakeResponse(payload={"result": "OK"})],
        ) as client:
            asyncio.run(redis_cache.get_or_set_json("scope", {"id": "1"}, loader, ttl_seconds=99))

        self.assertEqual(client.calls[-1][1]["json"][-2:], ["EX", 99])

    def test_invalidate_namespaces_bumps_unique_non_empty_versions(self):
        with patched_redis(
            enabled_settings(), [FakeResponse(payload={"result": 1}), FakeResponse(payload={"result": 2})]
        ) as client:
            asyncio.run(redis_cache.invalidate_namespaces("b", "", "a", "b"))

        commands = [call[1]["json"] for call in client.calls]
        self.assertEqual(commands, [["INCR", "polyu:v2:version:a"], ["INCR", "polyu:v2:version:b"]])

    def test_get_json_ignores_missing_invalid_and_non_dict_payloads(self):
        cases = (
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": "not-json"}),
            FakeResponse(payload={"result": json.dumps(["not", "dict"])}),
        )
        with patched_redis(enabled_settings(), cases):
            self.assertIsNone(asyncio.run(redis_cache.get_json("key")))
            self.assertIsNone(asyncio.run(redis_cache.get_json("key")))
            self.assertIsNone(asyncio.run(redis_cache.get_json("key")))

    def test_execute_returns_none_for_redis_failures(self):
        responses = (
            FakeResponse(status_code=500, payload={"error": "bad"}, text="bad"),
            FakeResponse(payload={"error": "ERR"}),
        )
        with patched_redis(enabled_settings(), responses):
            self.assertEqual(asyncio.run(redis_cache.get_version("items")), "0")
            self.assertIsNone(asyncio.run(redis_cache.get_json("key")))

    def test_cache_error_result_falls_back_to_loader(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patched_redis(
            enabled_settings(), [FakeResponse(status_code=500, payload={"error": "bad"}, text="bad")]
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_ERROR)
        loader.assert_awaited_once()

    def test_disabled_cache_result_bypasses_redis(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        with patch("app.services.cache.redis_cache.get_settings", return_value=make_settings()), patch.object(
            redis_cache, "_client", None
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_BYPASS)
        loader.assert_awaited_once()

    def test_client_lifecycle_creates_and_closes_async_client(self):
        client = FakeAsyncClient()
        with patch.object(redis_cache, "_client", None), patch(
            "app.services.cache.redis_cache.httpx.AsyncClient", return_value=client
        ):
            asyncio.run(redis_cache.initialize_client(enabled_settings()))
            self.assertIs(redis_cache._client, client)
            asyncio.run(redis_cache.close_client())

        self.assertTrue(client.is_closed)

    def test_disabled_client_initialization_is_a_noop(self):
        with patch.object(redis_cache, "_client", None):
            asyncio.run(redis_cache.initialize_client(make_settings()))
            self.assertIsNone(redis_cache._client)

    def test_execute_reports_missing_async_client(self):
        with patch(
            "app.services.cache.redis_cache.get_settings", return_value=enabled_settings()
        ), patch(
            "app.services.cache.redis_cache._get_client", new_callable=AsyncMock, return_value=None
        ):
            result = asyncio.run(redis_cache._execute_command(["GET", "key"]))
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "disabled")

    def test_set_response_cache_headers_writes_status_and_scope(self):
        response = Response()
        redis_cache.set_response_cache_headers(
            response,
            redis_cache.CacheResult({"value": "cached"}, redis_cache.CACHE_HIT, "scope"),
        )

        self.assertEqual(response.headers["X-Redis-Cache"], redis_cache.CACHE_HIT)
        self.assertEqual(response.headers["X-Redis-Cache-Scope"], "scope")

    def test_build_cache_key_is_stable_and_sensitive_to_versions(self):
        key_a = redis_cache.build_cache_key("scope", {"b": 2, "a": 1}, versions={"items": "1"})
        key_b = redis_cache.build_cache_key("scope", {"a": 1, "b": 2}, versions={"items": "1"})
        key_c = redis_cache.build_cache_key("scope", {"a": 1, "b": 2}, versions={"items": "2"})

        self.assertEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)
