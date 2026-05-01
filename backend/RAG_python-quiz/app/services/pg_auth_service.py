# -*- coding: utf-8 -*-
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import bcrypt

from app.services.pg_db import _get_conn
from app.logger import get_logger
from app.utils.jwt_utils import create_session_token, verify_token

logger = get_logger(__name__)


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
    with _get_conn() as conn, conn.cursor() as cur:
        # Query the user by email
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
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
        cur.execute(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (datetime.now(timezone.utc), user_id)
        )
        conn.commit()

        # Generate a JWT session token.
        # It is stateless and does not need to be stored in the database.
        # Use email as the username because JWT usually contains identifiable user information.
        session_token = create_session_token(
            user_id=str(user_id),  # Convert UUID to string
            username=email,
            expires_in_days=7  # Set the session validity period to 7 days. Adjust as needed.
        )

        logger.info(f"Session token created for user: {email} (user_id: {user_id})")

        # Build user information without including the password hash
        user_info = dict(row)
        user_info.pop("password_hash", None)  # Remove the password hash. Do not return it to the frontend.

        return {
            "message": "Login successful",
            "user": user_info,
            "session_token": session_token
        }


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


def logout(session_token: str) -> Dict[str, Any]:
    """
    Log out the user.

    JWT is stateless, so the client only needs to discard the token.

    Note:
        JWT cannot be actively revoked.
        Since this is a stateless design, the frontend only needs to discard the token.
        If forced revocation is required, an additional blacklist mechanism must be implemented.

    Args:
        session_token: JWT session token. It is not actually required for revocation.

    Returns:
        Dict with a message indicating success.
    """
    # Verify whether the token is valid.
    # This is optional and is used for logging.
    payload = verify_token(session_token)
    if payload:
        logger.info(f"User logout requested for user_id: {payload.get('sub')}")
    else:
        logger.warning(f"Logout attempted with invalid token")

    return {"message": "Logout successful. Please discard the token on client side."}


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

    # Validate password length.
    # bcrypt limits passwords to 72 bytes.
    password_bytes = password.encode('utf-8')

    with _get_conn() as conn, conn.cursor() as cur:
        # Check whether the email already exists
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"Email {email} is already registered")

        # Hash the password.
        # bcrypt automatically handles cases where the password exceeds 72 bytes.
        password_hash = _hash_password(password)

        # Insert the user record
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id, email, full_name, role, created_at
        """, (email, password_hash, full_name, role))

        user_row = cur.fetchone()
        user_id = user_row["id"]

        # Insert the corresponding child-table record based on the role
        if role == 'teacher':
            cur.execute("INSERT INTO teachers (user_id) VALUES (%s)", (user_id,))
        elif role == 'student':
            cur.execute("INSERT INTO students (user_id) VALUES (%s)", (user_id,))

        conn.commit()

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