from typing import Any

from app.logger import get_logger
from app.services.auth.passwords import hash_password, verify_password
from app.services.auth.refresh_tokens import (
    hash_refresh_token,
    new_refresh_token,
    refresh_token_expires_at,
)
from app.services.auth.repository import AuthRepository
from app.services.auth.tokens import build_token_response
from app.services.pg.pg_db import with_cursor
from app.utils.jwt_utils import verify_token

logger = get_logger(__name__)


class AuthService:
    def login(self, email: str, password: str, role: str | None = None) -> dict[str, Any]:
        with with_cursor(write=True) as cur:
            repository = AuthRepository(cur)
            row = repository.lookup_user(email)

            if not row:
                logger.warning(f"Login failed for email: {email} - user not found")
                raise ValueError("Invalid email or password")

            password_hash = row.get("password_hash")
            if not password_hash or not verify_password(password, password_hash):
                logger.warning(f"Login failed for email: {email} - invalid password")
                raise ValueError("Invalid email or password")

            if role is not None:
                if role not in ("teacher", "student"):
                    logger.warning(f"Login failed for email: {email} - invalid requested role: {role}")
                    raise ValueError("Invalid role requested")
                if row.get("role") != role:
                    logger.warning(
                        f"Login failed for email: {email} - role mismatch "
                        f"(requested: {role}, actual: {row.get('role')})"
                    )
                    raise ValueError("Role does not match")

            user_id = row.get("id")
            if not user_id:
                logger.error(f"User record missing ID for email: {email}")
                raise ValueError("User record is invalid")

            repository.mark_last_login(user_id)
            user_info = dict(row)
            user_info.pop("password_hash", None)
            refresh_token = new_refresh_token()
            repository.store_refresh_token(
                user_id=str(user_id),
                token_hash=hash_refresh_token(refresh_token),
                expires_at=refresh_token_expires_at(),
            )

        logger.info(f"Access and refresh tokens created for user: {email} (user_id: {user_id})")
        return build_token_response(
            message="Login successful",
            user_info=user_info,
            user_id=str(user_id),
            email=email,
            refresh_token=refresh_token,
        )

    def refresh_session(self, refresh_token: str) -> dict[str, Any]:
        if not refresh_token:
            raise ValueError("Invalid refresh token")

        next_refresh_token = new_refresh_token()
        next_expires_at = refresh_token_expires_at()
        with with_cursor(write=True) as cur:
            repository = AuthRepository(cur)
            user_row = repository.rotate_refresh_token(
                current_token_hash=hash_refresh_token(refresh_token),
                next_token_hash=hash_refresh_token(next_refresh_token),
                next_expires_at=next_expires_at,
            )

        if not user_row:
            logger.warning("Refresh token rotation failed: token is invalid, expired, or revoked")
            raise ValueError("Invalid refresh token")

        user_info = dict(user_row)
        user_id = str(user_info.get("id"))
        email = str(user_info.get("email"))
        return build_token_response(
            message="Token refreshed",
            user_info=user_info,
            user_id=user_id,
            email=email,
            refresh_token=next_refresh_token,
        )

    def verify_session(self, session_token: str) -> dict[str, Any] | None:
        payload = verify_token(session_token)
        return None if not payload else {
            "user_id": payload.get("sub"),
            "email": payload.get("username"),
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
        }

    def logout(self, refresh_token: str) -> dict[str, Any]:
        if not refresh_token:
            raise ValueError("Invalid refresh token")

        with with_cursor(write=True) as cur:
            repository = AuthRepository(cur)
            revoked = repository.revoke_refresh_token(hash_refresh_token(refresh_token))

        if not revoked:
            logger.warning("Logout attempted with invalid, expired, or already revoked refresh token")
            raise ValueError("Invalid refresh token")

        return {"message": "Logout successful"}

    def register(self, email: str, password: str, full_name: str, role: str) -> dict[str, Any]:
        if role not in ("teacher", "student"):
            raise ValueError(f"Invalid role: {role}. Must be 'teacher' or 'student'")

        with with_cursor(write=True) as cur:
            repository = AuthRepository(cur)
            if repository.email_exists(email):
                raise ValueError(f"Email {email} is already registered")

            user_row = repository.register_user(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                role=role,
            )
            if not user_row:
                raise ValueError("Registration failed")

            user_id = user_row["id"]
            logger.info(f"User registered: {email} (role: {role}, user_id: {user_id})")
            return {
                "message": "Registration successful",
                "user": dict(user_row),
            }


auth_service = AuthService()
