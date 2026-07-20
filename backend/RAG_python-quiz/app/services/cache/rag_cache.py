from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

from app.services.cache import redis_cache, studio_cache
from app.services.pg.rls_context import get_current_rls_user


RowsLoader = Callable[[], Awaitable[list[dict]]]
RowsRehydrator = Callable[[list[dict]], Awaitable[list[dict]]]


def normalize_query_text(question: str) -> str:
    return " ".join(question.strip().split())


def normalize_file_ids(selected_file_ids: Sequence[str]) -> list[str]:
    return sorted({str(file_id) for file_id in selected_file_ids if file_id})


async def get_or_set_query_embedding(
    model: Any,
    query_text: str,
    *,
    mode: str,
    settings: Any,
) -> list[float]:
    async def load() -> dict[str, Any]:
        return {"vector": await model.aembed_query(query_text)}

    if not _cache_enabled(settings, "rag_embedding_cache_enabled"):
        payload = (
            await redis_cache.load_without_cache("rag:query-embedding", load, reason="disabled")
        ).value
        vector = payload.get("vector")
        return vector if isinstance(vector, list) else await model.aembed_query(query_text)

    payload = await redis_cache.get_or_set_json(
        "rag:query-embedding",
        _model_cache_params(model, mode=mode, query_text=query_text),
        load,
        ttl_seconds=settings.rag_embedding_cache_ttl_seconds,
    )
    vector = payload.get("vector")
    return vector if isinstance(vector, list) else await model.aembed_query(query_text)


async def get_or_set_retrieval_rows(
    query_vector: list[float],
    *,
    query_text: str,
    selected_file_ids: Sequence[str],
    k: int,
    embedding_column: str,
    model: Any,
    mode: str,
    settings: Any,
    loader: RowsLoader,
    rehydrate: RowsRehydrator | None = None,
) -> list[dict]:
    user_id = get_current_rls_user() or ""
    async def load_without_compact_cache() -> dict[str, Any]:
        return {"rows": await loader()}

    if not user_id or not _cache_enabled(settings, "rag_retrieval_cache_enabled"):
        reason = "missing_user" if not user_id else "disabled"
        payload = (
            await redis_cache.load_without_cache(
                "rag:retrieval",
                load_without_compact_cache,
                reason=reason,
            )
        ).value
        rows = payload.get("rows")
        return rows if isinstance(rows, list) else await loader()

    loaded_rows: list[dict] | None = None

    async def load_compact() -> dict[str, Any]:
        nonlocal loaded_rows
        loaded_rows = await loader()
        return {"rows": compact_retrieval_rows(loaded_rows)}

    result = await redis_cache.get_or_set_json_with_status(
        "rag:retrieval",
        {
            "user_id": user_id,
            "query_text": query_text,
            "selected_file_ids": normalize_file_ids(selected_file_ids),
            "k": k,
            "embedding_column": embedding_column,
            "model_name": getattr(model, "model_name", ""),
            "base_url": getattr(model, "base_url", ""),
            "mode": mode,
        },
        load_compact,
        version_namespaces=[studio_cache.rag_retrieval_namespace()],
        ttl_seconds=settings.rag_retrieval_cache_ttl_seconds,
    )
    if loaded_rows is not None:
        return loaded_rows

    compact_rows = result.value.get("rows")
    if not is_valid_compact_rows(compact_rows) or rehydrate is None:
        return await loader()

    try:
        hydrated_rows = await rehydrate(compact_rows)
    except Exception:
        return await loader()
    if len(hydrated_rows) != len(compact_rows):
        return await loader()
    return hydrated_rows


def compact_retrieval_rows(rows: list[dict]) -> list[dict]:
    compact = []
    for row in rows:
        chunk_id = row.get("chunkId") or row.get("chunkid")
        if not chunk_id:
            continue
        score = row.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            continue
        compact.append({"chunkId": str(chunk_id), "score": score})
    return compact


def is_valid_compact_rows(rows: Any) -> bool:
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"chunkId", "score"}:
            return False
        if not row.get("chunkId"):
            return False
        if row["score"] is not None and not isinstance(row["score"], (int, float)):
            return False
    return True


def _model_cache_params(model: Any, *, mode: str, query_text: str) -> dict[str, Any]:
    return {
        "query_text": query_text,
        "model_name": getattr(model, "model_name", ""),
        "base_url": getattr(model, "base_url", ""),
        "mode": mode,
    }


def _cache_enabled(settings: Any, flag_name: str) -> bool:
    return bool(getattr(settings, flag_name, True) and redis_cache.is_enabled())
