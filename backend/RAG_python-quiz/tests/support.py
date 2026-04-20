from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def iterable_side_effect(values: Iterable[Any]):
    iterator = iter(values)

    def _next(*args, **kwargs):
        return next(iterator)

    return _next
