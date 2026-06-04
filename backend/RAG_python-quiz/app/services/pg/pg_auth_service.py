# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Dict, Optional
import bcrypt

from app.services.pg.pg_db import with_cursor
from app.logger import get_logger
from app.utils.jwt_utils import ACCESS_TOKEN_EXPIRES_SECONDS, create_access_token, verify_token

logger = get_logger(__name__)

REFRESH_TOKEN_EXPIRES_DAYS = 30
REFRESH_TOKEN_BYTES = 32


def login(email: str, password: str, role: Optional[str] = None) -> Dict[str, Any]:
    """
    User login. Verifies credentials and creates a JWT session token
    without requiring a sessions table.

    Args:
        email: User email address
        password: Plaintext password

    Returns:
        Dict containing message, user info, and session_token (JWT) if successful.
        Raises ValueError if login fails.
    """
    with with_cursor(write=True) as cur:
        # Query through a security-definer function so login works after users RLS is enabled.
        cur.execute("SELECT * FROM app_security.auth_lookup_user(%s::text)", (email,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"Login failed for email: {email} - user not found")
            raise ValueError("Invalid email or password")

        # Verify password
        password_hash = row.get("password_hash")
        if not password_hash or not _verify_password(password, password_hash):
            logger.warning(f"Login failed for email: {email} - invalid password")
            raise ValueError("Invalid email or password")

        # If the frontend provides a role, check whether it matches the role in the database
        db_role = row.get("role")
        if role is not None:
            if role not in ("teacher", "student"):
                logger.warning(f"Login failed for email: {email} - invalid requested role: {role}")
                raise ValueError("Invalid role requested")
            if db_role != role:
                logger.warning(f"Login failed for email: {email} - role mismatch (requested: {role}, actual: {db_role})")
                raise ValueError("Role does not match")

        user_id = row.get("id")
        if not user_id:
            logger.error(f"User record missing ID for email: {email}")
            raise ValueError("User record is invalid")

        # Update the last login time
        cur.execute("SELECT app_security.auth_mark_last_login(%s::uuid)", (user_id,))

        # Build user information without including the password hash
        user_info = dict(row)
        user_info.pop("password_hash", None)  # Remove the password hash. Do not return it to the frontend.

        refresh_token = _issue_refresh_token(cur, str(user_id))

    logger.info(f"Access and refresh tokens created for user: {email} (user_id: {user_id})")

    return _build_token_response(
        message="Login successful",
        user_info=user_info,
        user_id=str(user_id),
        email=email,
        refresh_token=refresh_token,
    )

def refresh_session(refresh_token: str) -> Dict[str, Any]:
    """Rotate a valid refresh token and return a fresh access/refresh token pair."""
    if not refresh_token:
        raise ValueError("Invalid refresh token")

    next_refresh_token = _new_refresh_token()
    next_expires_at = _refresh_token_expires_at()
    with with_cursor(write=True) as cur:
        cur.execute(
            "SELECT * FROM app_security.auth_rotate_refresh_token(%s::text, %s::text, %s::timestamptz)",
            (_hash_refresh_token(refresh_token), _hash_refresh_token(next_refresh_token), next_expires_at),
        )
        user_row = cur.fetchone()

    if not user_row:
        logger.warning("Refresh token rotation failed: token is invalid, expired, or revoked")
        raise ValueError("Invalid refresh token")

    user_info = dict(user_row)
    user_id = str(user_info.get("id"))
    email = str(user_info.get("email"))
    return _build_token_response(
        message="Token refreshed",
        user_info=user_info,
        user_id=user_id,
        email=email,
        refresh_token=next_refresh_token,
    )


def verify_session(session_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify whether the JWT session token is valid without querying the database.

    Args:
        session_token: The JWT session token to verify.

    Returns:
        If valid, returns a dictionary containing user_id (UUID) and email.
        If invalid or expired, returns None.
    """
    payload = verify_token(session_token)
    if payload:
        return {
            "user_id": payload.get("sub"),  # UUID string
            "email": payload.get("username"),  # The username stored in the JWT is actually the email
            "exp": payload.get("exp"),
            "iat": payload.get("iat")
        }
    return None


def logout(refresh_token: str) -> Dict[str, Any]:
    """Revoke a refresh token so it can no longer mint access tokens."""
    if not refresh_token:
        raise ValueError("Invalid refresh token")

    with with_cursor(write=True) as cur:
        cur.execute(
            "SELECT app_security.auth_revoke_refresh_token(%s::text) AS revoked",
            (_hash_refresh_token(refresh_token),),
        )
        row = cur.fetchone()

    if not row or not row.get("revoked"):
        logger.warning("Logout attempted with invalid, expired, or already revoked refresh token")
        raise ValueError("Invalid refresh token")

    return {"message": "Logout successful"}


def register(email: str, password: str, full_name: str, role: str) -> Dict[str, Any]:
    """
    User registration.

    Args:
        email: User email address
        password: Plaintext password.
                  Note: bcrypt limits passwords to a maximum of 72 bytes.
        full_name: User full name
        role: User role, either 'teacher' or 'student'

    Returns:
        Dict containing message and user info if successful.
        Raises ValueError if registration fails.
    """
    # Validate role
    if role not in ('teacher', 'student'):
        raise ValueError(f"Invalid role: {role}. Must be 'teacher' or 'student'")

    with with_cursor(write=True) as cur:
        cur.execute("SELECT app_security.auth_email_exists(%s::text) AS exists", (email,))
        existing = cur.fetchone()
        if existing and existing.get("exists"):
            raise ValueError(f"Email {email} is already registered")

        # Hash the password.
        # bcrypt automatically handles cases where the password exceeds 72 bytes.
        password_hash = _hash_password(password)

        # Registration goes through a security-definer function so users RLS can stay strict.
        cur.execute(
            "SELECT * FROM app_security.auth_register_user(%s::text, %s::text, %s::text, %s::text)",
            (email, password_hash, full_name, role),
        )
        user_row = cur.fetchone()
        if not user_row:
            raise ValueError("Registration failed")

        user_id = user_row["id"]

        logger.info(f"User registered: {email} (role: {role}, user_id: {user_id})")

        return {
            "message": "Registration successful",
            "user": dict(user_row)
        }


def _hash_password(password: str) -> str:
    """Use bcrypt to convert a plaintext password into a hashed string."""
    if not isinstance(password, str):
        raise TypeError("Password must be a string")

    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify whether the plaintext password matches the stored bcrypt hash."""
    if not isinstance(password, str):
        return False

    try:
        password_hash_bytes = (
            password_hash.encode("utf-8") if isinstance(password_hash, str) else password_hash
        )
        return bcrypt.checkpw(password.encode("utf-8"), password_hash_bytes)
    except ValueError as exc:
        logger.error("Failed to verify password: %s", exc)
        return False


def _build_token_response(
    *,
    message: str,
    user_info: Dict[str, Any],
    user_id: str,
    email: str,
    refresh_token: str,
) -> Dict[str, Any]:
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


def _issue_refresh_token(cur: Any, user_id: str) -> str:
    refresh_token = _new_refresh_token()
    cur.execute(
        "SELECT app_security.auth_store_refresh_token(%s::uuid, %s::text, %s::timestamptz)",
        (user_id, _hash_refresh_token(refresh_token), _refresh_token_expires_at()),
    )
    return refresh_token


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def _hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRES_DAYS)
