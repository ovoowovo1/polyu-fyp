from datetime import datetime
from typing import Any


class AuthRepository:
    """Boundary for app_security auth helper functions."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    def lookup_user(self, email: str) -> dict[str, Any] | None:
        return self._fetchone("SELECT * FROM app_security.auth_lookup_user(%s::text)", (email,))

    def mark_last_login(self, user_id: str) -> None:
        self._cursor.execute("SELECT app_security.auth_mark_last_login(%s::uuid)", (user_id,))

    def email_exists(self, email: str) -> bool:
        existing = self._fetchone("SELECT app_security.auth_email_exists(%s::text) AS exists", (email,))
        return bool(existing and existing.get("exists"))

    def register_user(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        role: str,
    ) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM app_security.auth_register_user(%s::text, %s::text, %s::text, %s::text)",
            (email, password_hash, full_name, role),
        )

    def store_refresh_token(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        self._cursor.execute(
            "SELECT app_security.auth_store_refresh_token(%s::uuid, %s::text, %s::timestamptz)",
            (user_id, token_hash, expires_at),
        )

    def rotate_refresh_token(
        self,
        *,
        current_token_hash: str,
        next_token_hash: str,
        next_expires_at: datetime,
    ) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM app_security.auth_rotate_refresh_token(%s::text, %s::text, %s::timestamptz)",
            (current_token_hash, next_token_hash, next_expires_at),
        )

    def revoke_refresh_token(self, token_hash: str) -> bool:
        row = self._fetchone(
            "SELECT app_security.auth_revoke_refresh_token(%s::text) AS revoked",
            (token_hash,),
        )
        return bool(row and row.get("revoked"))

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        self._cursor.execute(sql, params)
        return self._cursor.fetchone()
