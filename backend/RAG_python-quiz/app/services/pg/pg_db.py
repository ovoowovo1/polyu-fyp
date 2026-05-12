import psycopg2
import psycopg2.extras

from app.config import get_settings
from app.services.pg.rls_context import get_current_rls_user

def _get_conn():
    settings = get_settings()
    conn = psycopg2.connect(
        settings.pg_dsn,
        cursor_factory=psycopg2.extras.RealDictCursor,
        application_name="pg_service",
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )
    user_id = get_current_rls_user()
    if user_id:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
    return conn
