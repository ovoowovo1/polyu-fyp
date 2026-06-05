import bcrypt

from app.logger import get_logger

logger = get_logger(__name__)


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    if not isinstance(password, str):
        raise TypeError("Password must be a string")

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when the plaintext password matches the stored bcrypt hash."""
    if not isinstance(password, str):
        return False

    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8") if isinstance(password_hash, str) else password_hash,
        )
    except ValueError as exc:
        logger.error("Failed to verify password: %s", exc)
        return False
