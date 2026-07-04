import asyncio
import json
import unittest
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


class RedisCacheTests(unittest.TestCase):
    def test_disabled_cache_loads_without_redis(self):
        loader = AsyncMock(return_value={"value": 1})

        with patch("app.services.cache.redis_cache.get_settings", return_value=make_settings()), patch(
            "app.services.cache.redis_cache.requests.post"
        ) as post:
            result = asyncio.run(redis_cache.get_or_set_json("scope", {"id": "1"}, loader))

        self.assertEqual(result, {"value": 1})
        loader.assert_awaited_once()
        post.assert_not_called()
        self.assertFalse(redis_cache._is_enabled(make_settings()))

    def test_cache_hit_returns_cached_payload_without_loader(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": "4"}),
            FakeResponse(payload={"result": json.dumps({"value": "cached"})}),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ) as post:
            self.assertTrue(redis_cache.is_enabled())
            result = asyncio.run(
                redis_cache.get_or_set_json(
                    "scope",
                    {"id": "1"},
                    loader,
                    version_namespaces=["items"],
                )
            )

        self.assertEqual(result, {"value": "cached"})
        loader.assert_not_awaited()
        self.assertEqual(post.call_count, 2)

    def test_cache_hit_result_includes_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": json.dumps({"value": "cached"})}),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "cached"})
        self.assertEqual(result.status, redis_cache.CACHE_HIT)
        self.assertEqual(result.scope, "scope")
        loader.assert_not_awaited()

    def test_cache_miss_loads_and_sets_with_ttl(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": "OK"}),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings(redis_cache_ttl_seconds=0)), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ) as post:
            result = asyncio.run(
                redis_cache.get_or_set_json(
                    "scope",
                    {"id": "1"},
                    loader,
                    version_namespaces=["items"],
                )
            )

        self.assertEqual(result, {"value": "fresh"})
        loader.assert_awaited_once()
        set_command = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(set_command[0], "SET")
        self.assertEqual(set_command[-2:], ["EX", 1])

    def test_cache_miss_result_includes_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": "OK"}),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_MISS)
        loader.assert_awaited_once()

    def test_cache_set_failure_reports_error_status(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": None}),
            FakeResponse(status_code=500, payload={"error": "bad"}, text="bad"),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_ERROR)
        loader.assert_awaited_once()

    def test_cache_miss_can_override_ttl(self):
        loader = AsyncMock(return_value={"value": "fresh"})
        responses = [
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": "OK"}),
        ]

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings(redis_cache_ttl_seconds=30)), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ) as post:
            result = asyncio.run(redis_cache.get_or_set_json("scope", {"id": "1"}, loader, ttl_seconds=99))

        self.assertEqual(result, {"value": "fresh"})
        set_command = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(set_command[-2:], ["EX", 99])

    def test_invalidate_namespaces_bumps_unique_non_empty_versions(self):
        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            return_value=FakeResponse(payload={"result": 1}),
        ) as post:
            redis_cache.invalidate_namespaces("b", "", "a", "b")

        commands = [json.loads(call.kwargs["data"]) for call in post.call_args_list]
        self.assertEqual(commands, [["INCR", "polyu:v1:version:a"], ["INCR", "polyu:v1:version:b"]])

    def test_get_json_ignores_missing_invalid_and_non_dict_payloads(self):
        cases = (
            FakeResponse(payload={"result": None}),
            FakeResponse(payload={"result": "not-json"}),
            FakeResponse(payload={"result": json.dumps(["not", "dict"])}),
        )
        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=cases,
        ):
            self.assertIsNone(redis_cache.get_json("key"))
            self.assertIsNone(redis_cache.get_json("key"))
            self.assertIsNone(redis_cache.get_json("key"))

    def test_execute_returns_none_for_redis_failures(self):
        responses = (
            FakeResponse(status_code=500, payload={"error": "bad"}, text="bad"),
            FakeResponse(payload={"error": "ERR"}),
        )
        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            side_effect=responses,
        ):
            self.assertEqual(redis_cache.get_version("items"), "0")
            self.assertIsNone(redis_cache.get_json("key"))

    def test_cache_error_result_falls_back_to_loader(self):
        loader = AsyncMock(return_value={"value": "fresh"})

        with patch("app.services.cache.redis_cache.get_settings", return_value=enabled_settings()), patch(
            "app.services.cache.redis_cache.requests.post",
            return_value=FakeResponse(status_code=500, payload={"error": "bad"}, text="bad"),
        ):
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_ERROR)
        loader.assert_awaited_once()

    def test_disabled_cache_result_bypasses_redis(self):
        loader = AsyncMock(return_value={"value": "fresh"})

        with patch("app.services.cache.redis_cache.get_settings", return_value=make_settings()), patch(
            "app.services.cache.redis_cache.requests.post"
        ) as post:
            result = asyncio.run(redis_cache.get_or_set_json_with_status("scope", {"id": "1"}, loader))

        self.assertEqual(result.value, {"value": "fresh"})
        self.assertEqual(result.status, redis_cache.CACHE_BYPASS)
        loader.assert_awaited_once()
        post.assert_not_called()

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
