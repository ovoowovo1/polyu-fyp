"""Request-scoped PostgreSQL RLS identity."""

from __future__ import annotations

from contextvars import ContextVar


_current_user_id: ContextVar[str | None] = ContextVar("pg_rls_user_id", default=None)


def set_current_rls_user(user_id: str | None) -> None:
    _current_user_id.set(str(user_id) if user_id else None)


def get_current_rls_user() -> str | None:
    return _current_user_id.get()


def clear_current_rls_user() -> None:
    _current_user_id.set(None)

