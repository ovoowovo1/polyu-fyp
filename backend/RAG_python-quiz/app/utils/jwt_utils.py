from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.logger import get_logger
from app.routers.service_helpers import error_detail
from app.services.pg.rls_context import set_current_rls_user

logger = get_logger(__name__)

_http_bearer = HTTPBearer(auto_error=False)
ACCESS_TOKEN_EXPIRES_SECONDS = 15 * 60
_JWT_SECRET_PLACEHOLDERS = {
    "",
    "123456789",
    "change-me",
    "changeme",
    "replace-with-at-least-32-random-characters",
}


def _normalize_jwt_secret(raw_secret: str | None) -> str:
    secret = (raw_secret or "").strip()
    if secret.lower() in _JWT_SECRET_PLACEHOLDERS:
        raise RuntimeError("JWT_SECRET_KEY must be configured with a strong non-placeholder value")
    return secret


def create_access_token(user_id: str, username: str) -> str:
    """Create a short-lived signed JWT access token for an authenticated user."""
    settings = get_settings()
    secret_key = _normalize_jwt_secret(settings.jwt_secret_key)

    issued_at = datetime.utcnow()
    expires_at = issued_at + timedelta(seconds=ACCESS_TOKEN_EXPIRES_SECONDS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": issued_at,
        "exp": expires_at,
        "type": "access",
    }

    token = jwt.encode(payload, secret_key, algorithm="HS256")
    logger.debug(f"Created access token for user_id: {user_id}")
    return token


def create_session_token(user_id: str, username: str, expires_in_days: int = 7) -> str:
    """Backward-compatible wrapper for callers that still use the old name."""
    return create_access_token(user_id, username)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode a JWT access token, returning None when it is invalid."""
    settings = get_settings()
    try:
        secret_key = _normalize_jwt_secret(settings.jwt_secret_key)
    except RuntimeError as exc:
        logger.warning(str(exc))
        return None

    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            logger.warning("Token verification failed: token type is not access")
            return None
        logger.debug(f"Token verified for user_id: {payload.get('sub')}")
        return payload
    except JWTError as e:
        logger.warning(f"Token verification failed: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {str(e)}", exc_info=True)
        return None


def get_user_id_from_token(token: str) -> Optional[str]:
    """Extract the user id from a valid JWT session token."""
    payload = verify_token(token)
    if payload and "sub" in payload:
        return str(payload["sub"])
    return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> Dict[str, Any]:
    """FastAPI dependency that returns the authenticated user from a Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail=error_detail("Authorization header missing"))

    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail=error_detail("Invalid or expired token"))

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail=error_detail("Invalid token payload"))

    set_current_rls_user(str(user_id))
    return {
        "token": token,
        "user_id": str(user_id),
        "email": payload.get("username"),
        "payload": payload,
    }
