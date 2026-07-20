from contextlib import contextmanager
from threading import Lock
from typing import Any, Callable

import psycopg2
import psycopg2.extras
import psycopg2.pool

from app.config import get_settings
from app.services.pg.rls_context import get_current_rls_user


_pool = None
_pool_lock = Lock()


def set_rls_user(cur, user_id: str | None) -> None:
    """Bind an RLS user to the current transaction when one is available."""
    if user_id:
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))


def initialize_pool(settings=None):
    """Create the process-wide thread-safe PostgreSQL connection pool."""
    global _pool

    settings = settings or get_settings()
    min_size = int(getattr(settings, "pg_pool_min_size", 1))
    max_size = int(getattr(settings, "pg_pool_max_size", 10))
    if min_size < 1 or max_size < min_size:
        raise ValueError("pg_pool_min_size must be >= 1 and <= pg_pool_max_size")

    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                min_size,
                max_size,
                settings.pg_dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
                application_name="pg_service",
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
        return _pool


def close_pool() -> None:
    """Close all pooled connections and make the pool available for reinitialization."""
    global _pool

    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        pool.closeall()


def _get_pool():
    with _pool_lock:
        pool = _pool
    return pool or initialize_pool()


@contextmanager
def _get_conn(user_id: str | None = None):
    """Borrow one connection, bind RLS for the transaction, then return it safely."""
    pool = _get_pool()
    conn = pool.getconn()
    reusable = True
    try:
        # A previous user must never leak an open transaction into this request.
        conn.rollback()
        rls_user_id = str(user_id) if user_id else get_current_rls_user()
        if rls_user_id:
            with conn.cursor() as cur:
                set_rls_user(cur, rls_user_id)

        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            reusable = False
        raise
    finally:
        if getattr(conn, "closed", 0):
            reusable = False
        pool.putconn(conn, close=not reusable)


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
