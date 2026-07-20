import unittest
from unittest.mock import AsyncMock, patch

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
            rag_retrieval_cache_enabled=True,
            **overrides,
        )

    def test_normalizers_are_stable(self):
        self.assertEqual(rag_cache.normalize_query_text("  hello   world  "), "hello world")
        self.assertEqual(rag_cache.normalize_file_ids(["b", "a", "a", "", None]), ["a", "b"])

    def test_compact_retrieval_rows_discards_invalid_rows_and_sensitive_fields(self):
        rows = rag_cache.compact_retrieval_rows(
            [
                {"chunkId": "chunk-1", "score": "0.4", "text": "secret"},
                {"chunkid": "chunk-2", "score": None, "image_data": "base64"},
                {"text": "missing id", "score": 0.2},
                {"chunkId": "bad-score", "score": "not-a-number"},
            ]
        )

        self.assertEqual(rows, [{"chunkId": "chunk-1", "score": 0.4}, {"chunkId": "chunk-2", "score": None}])

    def test_compact_retrieval_payload_validation_rejects_untrusted_shapes(self):
        self.assertFalse(rag_cache.is_valid_compact_rows("bad"))
        self.assertFalse(rag_cache.is_valid_compact_rows([{"chunkId": "id", "score": 0.1, "text": "secret"}]))
        self.assertFalse(rag_cache.is_valid_compact_rows([{"chunkId": "", "score": 0.1}]))
        self.assertFalse(rag_cache.is_valid_compact_rows([{"chunkId": "id", "score": "0.1"}]))
        self.assertTrue(rag_cache.is_valid_compact_rows([]))

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
        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"vector": "bad"},
        ):
            vector = await rag_cache.get_or_set_query_embedding(model, "hello", mode="primary", settings=self.enabled_settings())

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

    async def test_retrieval_cache_hit_rehydrates_only_compact_rows(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])
        rehydrate = AsyncMock(
            return_value=[{"chunkId": "chunk-cache", "score": 0.2, "text": "full text", "image_data": "base64"}]
        )
        result = rag_cache.redis_cache.CacheResult(
            {"rows": [{"chunkId": "chunk-cache", "score": 0.2}]},
            rag_cache.redis_cache.CACHE_HIT,
            "rag:retrieval",
        )

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json_with_status",
            new_callable=AsyncMock,
            return_value=result,
        ) as get_or_set:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2], query_text="hello", selected_file_ids=["file-1"], k=20,
                embedding_column="embedding", model=model, mode="primary", settings=self.enabled_settings(),
                loader=loader, rehydrate=rehydrate,
            )

        self.assertEqual(rows[0]["text"], "full text")
        loader.assert_not_awaited()
        rehydrate.assert_awaited_once_with([{"chunkId": "chunk-cache", "score": 0.2}])
        self.assertEqual(get_or_set.call_args.kwargs["version_namespaces"], ["rag:retrieval"])

    async def test_retrieval_cache_miss_stores_only_chunk_id_and_score(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1, 0.2])
        loader = AsyncMock(return_value=[
            {"chunkId": "chunk-db", "score": 0.12, "text": "secret", "image_data": "base64"},
        ])

        async def load_through(_scope, _params, loader_func, **_kwargs):
            value = await loader_func()
            return rag_cache.redis_cache.CacheResult(value, rag_cache.redis_cache.CACHE_MISS, "rag:retrieval")

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json_with_status",
            new_callable=AsyncMock,
            side_effect=load_through,
        ) as get_or_set:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1, 0.2], query_text="hello", selected_file_ids=["file-b", "file-a", "file-a"], k=9,
                embedding_column="embedding", model=model, mode="primary", settings=self.enabled_settings(),
                loader=loader, rehydrate=AsyncMock(),
            )

        self.assertEqual(rows[0]["text"], "secret")
        payload = get_or_set.call_args.args[2]
        compact = await payload()
        self.assertEqual(compact, {"rows": [{"chunkId": "chunk-db", "score": 0.12}]})
        self.assertNotIn("text", compact["rows"][0])
        self.assertNotIn("image_data", compact["rows"][0])
        params = get_or_set.call_args.args[1]
        self.assertEqual(params["selected_file_ids"], ["file-a", "file-b"])
        self.assertEqual(params["user_id"], "user-1")

    async def test_retrieval_cache_key_includes_user_id(self):
        model = SuccessfulQueryModel("google/gemini-embedding-001", [0.1])
        result = rag_cache.redis_cache.CacheResult({"rows": []}, rag_cache.redis_cache.CACHE_HIT, "rag:retrieval")

        with patch("app.services.cache.rag_cache.get_current_rls_user", side_effect=["user-1", "user-2"]), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json_with_status",
            new_callable=AsyncMock,
            return_value=result,
        ) as get_or_set:
            for _ in range(2):
                await rag_cache.get_or_set_retrieval_rows(
                    [0.1], query_text="hello", selected_file_ids=["file-1"], k=1,
                    embedding_column="embedding", model=model, mode="primary", settings=self.enabled_settings(),
                    loader=AsyncMock(return_value=[]), rehydrate=AsyncMock(return_value=[]),
                )

        self.assertEqual(get_or_set.await_args_list[0].args[1]["user_id"], "user-1")
        self.assertEqual(get_or_set.await_args_list[1].args[1]["user_id"], "user-2")

    async def test_primary_and_fallback_modes_are_separate(self):
        primary = SuccessfulQueryModel("google/gemini-embedding-001", [0.1])
        fallback = SuccessfulQueryModel("google/gemini-embedding-2-preview", [0.2])
        with patch("app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json",
            new_callable=AsyncMock,
            return_value={"vector": [0.9]},
        ) as get_or_set:
            await rag_cache.get_or_set_query_embedding(primary, "hello", mode="primary", settings=self.enabled_settings())
            await rag_cache.get_or_set_query_embedding(fallback, "hello", mode="fallback", settings=self.enabled_settings())

        self.assertEqual(get_or_set.await_args_list[0].args[1]["mode"], "primary")
        self.assertEqual(get_or_set.await_args_list[1].args[1]["mode"], "fallback")

    async def test_retrieval_bad_payload_falls_back_to_loader(self):
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])
        result = rag_cache.redis_cache.CacheResult({"rows": "bad"}, rag_cache.redis_cache.CACHE_HIT, "rag:retrieval")
        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
            "app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True
        ), patch(
            "app.services.cache.rag_cache.redis_cache.get_or_set_json_with_status",
            new_callable=AsyncMock,
            return_value=result,
        ):
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1], query_text="hello", selected_file_ids=["file-1"], k=20,
                embedding_column="embedding", model=SuccessfulQueryModel("m", [0.1]), mode="primary",
                settings=self.enabled_settings(), loader=loader, rehydrate=AsyncMock(),
            )

        self.assertEqual(rows, [{"chunkId": "chunk-db"}])
        loader.assert_awaited_once()

    async def test_retrieval_cache_rehydrate_failure_and_partial_result_fall_back(self):
        for rehydrate in (AsyncMock(side_effect=RuntimeError("db down")), AsyncMock(return_value=[])):
            loader = AsyncMock(return_value=[{"chunkId": "fresh"}])
            result = rag_cache.redis_cache.CacheResult(
                {"rows": [{"chunkId": "cached", "score": 0.1}]},
                rag_cache.redis_cache.CACHE_HIT,
                "rag:retrieval",
            )
            with patch("app.services.cache.rag_cache.get_current_rls_user", return_value="user-1"), patch(
                "app.services.cache.rag_cache.redis_cache.is_enabled", return_value=True
            ), patch(
                "app.services.cache.rag_cache.redis_cache.get_or_set_json_with_status",
                new_callable=AsyncMock,
                return_value=result,
            ):
                rows = await rag_cache.get_or_set_retrieval_rows(
                    [0.1], query_text="hello", selected_file_ids=["file-1"], k=1,
                    embedding_column="embedding", model=SuccessfulQueryModel("m", [0.1]), mode="primary",
                    settings=self.enabled_settings(), loader=loader, rehydrate=rehydrate,
                )
            self.assertEqual(rows, [{"chunkId": "fresh"}])
            loader.assert_awaited_once()

    async def test_retrieval_cache_bypasses_when_user_is_missing(self):
        loader = AsyncMock(return_value=[{"chunkId": "chunk-db"}])

        async def load_without_cache(scope, loader_func, *, reason):
            return rag_cache.redis_cache.CacheResult(
                await loader_func(), rag_cache.redis_cache.CACHE_BYPASS, scope
            )

        with patch("app.services.cache.rag_cache.get_current_rls_user", return_value=""), patch(
            "app.services.cache.rag_cache.redis_cache.load_without_cache",
            new_callable=AsyncMock,
            side_effect=load_without_cache,
        ) as bypass:
            rows = await rag_cache.get_or_set_retrieval_rows(
                [0.1], query_text="hello", selected_file_ids=["file-1"], k=20,
                embedding_column="embedding", model=SuccessfulQueryModel("m", [0.1]), mode="primary",
                settings=self.enabled_settings(), loader=loader,
            )

        self.assertEqual(rows, [{"chunkId": "chunk-db"}])
        loader.assert_awaited_once()
        self.assertEqual(bypass.call_args.kwargs["reason"], "missing_user")
