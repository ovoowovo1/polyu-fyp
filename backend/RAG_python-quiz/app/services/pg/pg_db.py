from contextlib import contextmanager
from typing import Any, Callable

import psycopg2
import psycopg2.extras

from app.config import get_settings
from app.services.pg.rls_context import get_current_rls_user


def set_rls_user(cur, user_id: str | None) -> None:
    """Bind an RLS user to the current transaction when one is available."""
    if user_id:
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))


def _get_conn(user_id: str | None = None):
    settings = get_settings()
    conn = psycopg2.connect(
        settings.pg_dsn,
        cursor_factory=psycopg2.extras.RealDictCursor,
        application_name="pg_service",
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )
    rls_user_id = str(user_id) if user_id else get_current_rls_user()
    if rls_user_id:
        with conn.cursor() as cur:
            set_rls_user(cur, rls_user_id)
    return conn


@contextmanager
def with_cursor(*, write: bool = False):
    with _get_conn() as conn, conn.cursor() as cur:
        yield cur
        if write:
            conn.commit()


def fetch_one(sql: str, params: Any = None) -> Any:
    with with_cursor() as cur:
        return fetch_one_with_cursor(cur, sql, params)


def fetch_all(sql: str, params: Any = None) -> list[Any]:
    with with_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute_returning(sql: str, params: Any = None, *, commit: bool = True) -> Any:
    with with_cursor(write=commit) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_one_with_cursor(cur: Any, sql: str, params: Any = None) -> Any:
    cur.execute(sql, params)
    return cur.fetchone()


def fetch_bool(sql: str, params: Any = None, *, column: str) -> bool:
    row = fetch_one(sql, params)
    return bool(row and row.get(column))


def fetch_bool_with_cursor(cur: Any, sql: str, params: Any = None, *, column: str) -> bool:
    row = fetch_one_with_cursor(cur, sql, params)
    return bool(row and row.get(column))


def require_row(sql: str, params: Any = None, *, error: Exception, write: bool = False) -> Any:
    row = execute_returning(sql, params) if write else fetch_one(sql, params)
    if not row:
        raise error
    return row


def map_rows(sql: str, params: Any = None, *, mapper: Callable[[Any], Any]) -> list[Any]:
    return [mapper(row) for row in fetch_all(sql, params)]
