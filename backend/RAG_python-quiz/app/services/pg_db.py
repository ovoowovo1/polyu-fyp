import psycopg2
import psycopg2.extras

from app.config import get_settings

def _get_conn():
    settings = get_settings()
    return psycopg2.connect(
        settings.pg_dsn,
        cursor_factory=psycopg2.extras.RealDictCursor,
        application_name="pg_service",
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )
