from unittest.mock import AsyncMock, patch
import unittest

from app.services.cache import rag_cache
from tests.support import make_embedding_settings


class SuccessfulQueryModel:
    def __init__(self, model_name, vector, *, base_url="https://openrouter.ai/api/v1"):
        self.model_name = model_name
        self.base_url = base_url
        self.vector = vector
        self.calls = []

    async def aembed_query(self, text):
        self.calls.append(text)
        return self.vector


class RagCacheTests(unittest.IsolatedAsyncioTestCase):
    def enabled_settings(self, **overrides):
        return make_embedding_settings(
            redis_cache_enabled=True,
            upstash_redis_rest_url="https://redis.example",
            upstash_redis_rest_token="token",
            **overrides,
        )

    def test_normalizers_are_stable(self):
        self.assertEqual(rag_cache.normalize_query_text("  hello   world  "), "hello world")
        self.assertEqual(rag_cache.normalize_file_ids(["b", "a", "a", "", None]), ["a", "b"])

    async def test_query_embedding_cache_hit_skips_embedding_api(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()

        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"vector": [0.9, 0.8]},
        ) as get_or_set:
            vector = await rag_cache.get_or_set_query_embedding(model, "hello", mode="primary", settings=settings)

        self.assertEqual(vector, [0.9, 0.8])
        self.assertEqual(model.calls, [])
        self.assertEqual(get_or_set.call_args.args[0], "rag:query-embedding")
        self.assertEqual(get_or_set.call_args.args[1]["mode"], "primary")
        self.assertEqual(get_or_set.call_args.kwargs["ttl_seconds"], 3600)

    async def test_query_embedding_cache_miss_loads_embedding(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()

        async def load_through(_scope, _params, loader, **_kwargs):
            return await loader()

        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            side_effect=load_through,
        ) as get_or_set:
            vector = await rag_cache.get_or_set_query_embedding(model, "hello", mode="primary", settings=settings)

        self.assertEqual(vector, [0.1, 0.2])
        self.assertEqual(model.calls, ["hello"])
        self.assertEqual(get_or_set.call_args.kwargs["ttl_seconds"], 3600)

    async def test_query_embedding_bad_payload_falls_back_to_embedding_api(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()

        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"vector": "bad"},
        ):
            vector = await rag_cache.get_or_set_query_embedding(model, "hello", mode="primary", settings=settings)

        self.assertEqual(vector, [0.1, 0.2])
        self.assertEqual(model.calls, ["hello"])

    async def test_query_embedding_cache_disabled_logs_bypass_and_loads_embedding(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings(rag_embedding_cache_enabled=False)

        async def load_without_cache(scope, loader, *, reason):
            return rag_cache.redis_cache.CacheResult(await loader(), rag_cache.redis_cache.CACHE_BYPASS, scope)

        with patch(
            "app.services.cache.rag_cache.redis_cache.load_without_cache",
            new_callable=AsyncMock,
            side_effect=load_without_cache,
        ) as bypass:
            vector = await rag_cache.get_or_set_query_embedding(model, "hello", mode="primary", settings=settings)

        self.assertEqual(vector, [0.1, 0.2])
        self.assertEqual(model.calls, ["hello"])
        self.assertEqual(bypass.call_args.args[0], "rag:query-embedding")
        self.assertEqual(bypass.call_args.kwargs["reason"], "disabled")

    async def test_retrieval_cache_hit_skips_loader(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled",
            return_value=True,
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"rows": [{"chunkId": "chunk-cache"}]},
        ) as get_or_set:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2],
                query_text="hello",
                selected_file_ids=["file-1"],
                k=20,
                embedding_column="embedding",
                model=model,
                mode="primary",
                settings=settings,
                loader=loader,
            )

        self.assertEqual(rows, [{"chunkId": "chunk-cache"}])
        loader.assert_not_awaited()
        self.assertEqual(get_or_set.call_args.args[0], "rag:retrieval")
        self.assertEqual(get_or_set.call_args.kwargs["version_namespaces"], ["rag:retrieval"])
        self.assertEqual(get_or_set.call_args.kwargs["ttl_seconds"], 300)

    async def test_retrieval_cache_miss_loads_rows_and_normalizes_params(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])

        async def load_through(_scope, _params, loader_func, **_kwargs):
            return await loader_func()

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled",
            return_value=True,
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            side_effect=load_through,
        ) as get_or_set:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2],
                query_text="hello",
                selected_file_ids=["file-b", "file-a", "file-a"],
                k=9,
                embedding_column="embedding",
                model=model,
                mode="primary",
                settings=settings,
                loader=loader,
            )

        self.assertEqual(rows, [{"chunkId": "chunk-db"}])
        loader.assert_awaited_once()
        params = get_or_set.call_args.args[1]
        self.assertEqual(params["selected_file_ids"], ["file-a", "file-b"])
        self.assertEqual(params["user_id"], "user-1")
        self.assertEqual(params["mode"], "primary")

    async def test_retrieval_cache_key_includes_user_id(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1])
        settings = self.enabled_settings()

        with patch(
            "app.services.cache.rag_cache.get_current_rls_user",
            side_effect=["user-1", "user-2"],
        ), patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"rows": []},
        ) as get_or_set:
            for _ in range(2):
                await rag_cache.get_or_set_retrieval_rows(
                    [0.1],
                    query_text="hello",
                    selected_file_ids=["file-1"],
                    k=1,
                    embedding_column="embedding",
                    model=model,
                    mode="primary",
                    settings=settings,
                    loader=AsyncMock(return_value=[]),
                )

        self.assertEqual(get_or_set.await_args_list[0].args[1]["user_id"], "user-1")
        self.assertEqual(get_or_set.await_args_list[1].args[1]["user_id"], "user-2")

    async def test_primary_and_fallback_modes_are_separate(self):
        primary = SuccessfulQueryModel("google/gemini-embedding-001", [0.1])
        fallback = SuccessfulQueryModel("google/gemini-embedding-2-preview", [0.2])
        settings = self.enabled_settings()

        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"vector": [0.9]},
        ) as get_or_set:
            await rag_cache.get_or_set_query_embedding(primary, "hello", mode="primary", settings=settings)
            await rag_cache.get_or_set_query_embedding(fallback, "hello", mode="fallback", settings=settings)

        self.assertEqual(get_or_set.await_args_list[0].args[1]["mode"], "primary")
        self.assertEqual(get_or_set.await_args_list[1].args[1]["mode"], "fallback")

    async def test_retrieval_bad_payload_falls_back_to_loader(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled",
            return_value=True,
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"rows": "bad"},
        ):
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2],
                query_text="hello",
                selected_file_ids=["file-1"],
                k=20,
                embedding_column="embedding",
                model=model,
                mode="primary",
                settings=settings,
                loader=loader,
            )

        self.assertEqual(rows, [{"chunkId": "chunk-db"}])
        loader.assert_awaited_once()

    async def test_retrieval_cache_bypasses_when_user_is_missing(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        settings = self.enabled_settings()
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])

        async def load_without_cache(scope, loader_func, *, reason):
            return rag_cache.redis_cache.CacheResult(await loader_func(), rag_cache.redis_cache.CACHE_BYPASS, scope)

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value=""), patch(
            "app.services.cache.rag_cache.redis_cache.load_without_cache",
            new_callable=AsyncMock,
            side_effect=load_without_cache,
        ) as bypass:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2],
                query_text="hello",
                selected_file_ids=["file-1"],
                k=20,
                embedding_column="embedding",
                model=model,
                mode="primary",
                settings=settings,
                loader=loader,
            )

        self.assertEqual(rows, [{"chunkId": "chunk-db"}])
        loader.assert_awaited_once()
        self.assertEqual(bypass.call_args.args[0], "rag:retrieval")
        self.assertEqual(bypass.call_args.kwargs["reason"], "missing_user")
