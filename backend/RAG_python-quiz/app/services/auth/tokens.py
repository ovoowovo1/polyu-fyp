from typing import Any

from app.config import get_settings
from app.utils.jwt_utils import (
    ACCESS_TOKEN_EXPIRES_SECONDS,
    _normalize_jwt_secret,
    create_access_token,
)


def validate_jwt_secret_config(settings: Any = None) -> None:
    """Fail fast when JWT_SECRET_KEY is missing or still a placeholder."""
    _normalize_jwt_secret((settings or get_settings()).jwt_secret_key)


def build_token_response(
    *,
    message: str,
    user_info: dict[str, Any],
    user_id: str,
    email: str,
    refresh_token: str,
) -> dict[str, Any]:
    access_token = create_access_token(user_id=user_id, username=email)
    return {
        "message": message,
        "user": user_info,
        "session_token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": ACCESS_TOKEN_EXPIRES_SECONDS,
        "token_type": "Bearer",
    }
