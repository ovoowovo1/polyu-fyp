from datetime import datetime, timedelta, timezone
import hashlib
import secrets

REFRESH_TOKEN_EXPIRES_DAYS = 30
REFRESH_TOKEN_BYTES = 32


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRES_DAYS)

