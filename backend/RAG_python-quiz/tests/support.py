from __future__ import annotations

import json
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.schemas import ExamQuestion
from app.utils import api_key_manager
from app.utils.ingest_errors import EmbeddingProviderError


def build_app(*routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    return app


def build_client(*routers) -> TestClient:
    return TestClient(build_app(*routers))


@dataclass
class FakeCursor:
    fetchone_results: list[Any] = field(default_factory=list)
    fetchall_results: list[Any] = field(default_factory=list)
    executed: list[tuple[str, Any]] = field(default_factory=list)
    rowcount: int = 0

    def execute(self, sql: str, params: Any = None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@dataclass
class FakeConnection:
    cursor_obj: FakeCursor
    committed: bool = False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def with_auth(app: FastAPI, dependency, user: dict[str, Any]) -> FastAPI:
    app.dependency_overrides[dependency] = lambda: user
    return app


def build_authed_client(router, dependency, user: dict[str, Any]):
    app = with_auth(build_app(router), dependency, user)
    return app, TestClient(app)


def start_patches(testcase: unittest.TestCase, *patchers):
    started = []
    for patcher in patchers:
        started.append(patcher.start())
        testcase.addCleanup(patcher.stop)
    return tuple(started)


def capture_execute_values():
    captured = {}

    def fake_execute_values(cur, sql, rows, template=None):
        captured["sql"] = sql
        captured["rows"] = rows
        captured["template"] = template

    return captured, fake_execute_values


class EventRecorder:
    def __init__(self):
        self.events = []

    async def emit(self, message, data=None, event_type="retrieval"):
        self.events.append((message, data, event_type))


def make_chat_client(*responses):
    create = Mock(return_value=responses[0]) if len(responses) == 1 else Mock(side_effect=list(responses))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def make_completion_response(*, finish_reason="stop", choices=True):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason)] if choices else None
    )


def make_message_response(content="unused", **message_overrides):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, **message_overrides))]
    )


def make_openai_response(*, choices, model="test-model"):
    return SimpleNamespace(model=model, choices=choices)


def make_openai_choice(*, content=None, finish_reason="stop", refusal=None, include_message=True):
    message = SimpleNamespace(content=content, refusal=refusal) if include_message else None
    return SimpleNamespace(message=message, finish_reason=finish_reason)


async def fake_llm_retry(_name, func, *args, error_type=RuntimeError):
    return await func("api-key", *args)


def make_retrieval_doc(text, *, chunk_id="chunk-1", source="doc.pdf", page=1, file_id="file-1", score=0.12):
    return {
        "text": text,
        "source": source,
        "page": page,
        "fileId": file_id,
        "chunkId": chunk_id,
        "score": score,
    }


def make_exam_question(**overrides):
    data = {
        "question_id": "q-1",
        "question_type": "multiple_choice",
        "bloom_level": "remember",
        "question_text": "What is SQL?",
        "choices": ["A", "B", "C", "D"],
        "correct_answer_index": 1,
        "model_answer": None,
        "marks": 1,
        "marking_scheme": [],
        "rationale": "Basic recall",
        "image_description": None,
        "image_path": None,
        "source_chunk_ids": [],
    }
    data.update(overrides)
    return ExamQuestion(**data)


class ApiKeyManagerBase(unittest.TestCase):
    def setUp(self):
        self.original_llm_keys = list(api_key_manager._llm_keys)
        self.original_llm_index = api_key_manager._llm_index

    def set_llm_keys(self, keys, *, index=0):
        api_key_manager._llm_keys = list(keys)
        api_key_manager._llm_index = index

    def tearDown(self):
        api_key_manager._llm_keys = self.original_llm_keys
        api_key_manager._llm_index = self.original_llm_index


class FakeResponse:
    def __init__(self, status_code=200, payload=None, *, text=None, reason="OK", json_error=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if text is None else text
        self.reason = reason
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


def make_settings(**overrides):
    settings = {
        "embedding_api_key": "",
        "embedding_base_url": "",
        "embedding_model": "",
        "embedding_fallback_model": "",
        "embedding_fallback_column": "embedding_v2",
        "embedding_active_column": "embedding",
        "fulltext_search_backend": "pg_search",
        "llm_model": "",
        "llm_api_key": "",
        "llm_api_keys": "",
        "llm_base_url": "",
        "eval_llm_api_key": "",
        "eval_llm_base_url": "",
        "eval_llm_model": "",
        "eval_embedding_api_key": "",
        "eval_embedding_base_url": "",
        "eval_embedding_model": "",
        "jwt_secret_key": "test-secret",
        "cors_origins": ["*"],
        "port": 3000,
        "pg_dsn": "",
    }
    settings.update(overrides)
    return SimpleNamespace(**settings)


def make_embedding_settings(**overrides):
    settings = {
        "embedding_api_key": "test-key",
        "embedding_base_url": "https://openrouter.ai/api/v1",
        "embedding_model": "google/gemini-embedding-001",
        "embedding_active_column": "embedding_v2",
        "llm_model": "gemini-2.5-flash",
    }
    settings.update(overrides)
    return make_settings(**settings)


def make_embedding_error(
    raw_preview=None,
    *,
    upstream_message="No successful provider responses.",
    retryable=True,
):
    if raw_preview is None:
        raw_preview = f'{{"error":{{"message":"{upstream_message}","code":404}}}}'
    return EmbeddingProviderError(
        code="EMBEDDING_UPSTREAM_FAILED",
        message=f"Embedding upstream failed: {upstream_message}",
        retryable=retryable,
        provider="openrouter",
        model="google/gemini-embedding-001",
        base_url="https://openrouter.ai/api/v1",
        http_status=200,
        upstream_code=404,
        upstream_message=upstream_message,
        raw_preview=raw_preview,
    )
