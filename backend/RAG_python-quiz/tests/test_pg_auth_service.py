import unittest
from unittest.mock import patch

from app.services import pg_auth_service
from tests.support import FakeConnection, FakeCursor


class PgAuthServiceTests(unittest.TestCase):
    def test_login_success_updates_last_login_and_returns_token(self):
        cursor = FakeCursor(fetchone_results=[{"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}])
        conn = FakeConnection(cursor)

        with patch("app.services.pg_auth_service._get_conn", return_value=conn), patch(
            "app.services.pg_auth_service.create_session_token",
            return_value="jwt-token",
        ):
            result = pg_auth_service.login("u@example.com", "secret", "teacher")

        self.assertEqual(result["session_token"], "jwt-token")
        self.assertTrue(conn.committed)
        self.assertNotIn("password_hash", result["user"])

    def test_login_raises_when_user_missing(self):
        with patch("app.services.pg_auth_service._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[None]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret")

    def test_login_raises_for_invalid_password(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg_auth_service._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "wrong")

    def test_login_rejects_invalid_requested_role(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg_auth_service._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret", "admin")

    def test_login_rejects_role_mismatch(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg_auth_service._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret", "student")

    def test_login_rejects_missing_user_id(self):
        row = {"id": None, "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg_auth_service._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret")

    def test_verify_session_returns_normalized_payload(self):
        with patch("app.services.pg_auth_service.verify_token", return_value={"sub": "user-1", "username": "u@example.com", "exp": 1, "iat": 2}):
            self.assertEqual(
                pg_auth_service.verify_session("token"),
                {"user_id": "user-1", "email": "u@example.com", "exp": 1, "iat": 2},
            )

    def test_verify_session_returns_none_for_invalid_token(self):
        with patch("app.services.pg_auth_service.verify_token", return_value=None):
            self.assertIsNone(pg_auth_service.verify_session("token"))

    def test_logout_logs_out_even_for_invalid_token(self):
        with patch("app.services.pg_auth_service.verify_token", return_value=None):
            result = pg_auth_service.logout("token")

        self.assertIn("Logout successful", result["message"])

    def test_logout_logs_out_valid_session_token(self):
        with patch("app.services.pg_auth_service.verify_token", return_value={"sub": "user-1"}):
            result = pg_auth_service.logout("token")

        self.assertIn("Logout successful", result["message"])

    def test_register_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            pg_auth_service.register("u@example.com", "secret", "User", "admin")

    def test_register_rejects_existing_email(self):
        cursor = FakeCursor(fetchone_results=[{"id": "user-1"}])
        conn = FakeConnection(cursor)
        with patch("app.services.pg_auth_service._get_conn", return_value=conn):
            with self.assertRaises(ValueError):
                pg_auth_service.register("u@example.com", "secret", "User", "student")

    def test_register_creates_teacher_and_commits(self):
        cursor = FakeCursor(
            fetchone_results=[
                None,
                {"id": "user-1", "email": "u@example.com", "full_name": "User", "role": "teacher", "created_at": "now"},
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg_auth_service._get_conn", return_value=conn):
            result = pg_auth_service.register("u@example.com", "secret", "User", "teacher")

        self.assertEqual(result["user"]["role"], "teacher")
        self.assertTrue(conn.committed)

    def test_register_creates_student_and_commits(self):
        cursor = FakeCursor(
            fetchone_results=[
                None,
                {"id": "user-2", "email": "s@example.com", "full_name": "Student", "role": "student", "created_at": "now"},
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg_auth_service._get_conn", return_value=conn):
            result = pg_auth_service.register("s@example.com", "secret", "Student", "student")

        self.assertEqual(result["user"]["role"], "student")
        self.assertTrue(conn.committed)

    def test_hash_password_requires_string(self):
        with self.assertRaises(TypeError):
            pg_auth_service._hash_password(123)  # type: ignore[arg-type]

    def test_verify_password_handles_non_string_password(self):
        self.assertFalse(pg_auth_service._verify_password(123, "hash"))  # type: ignore[arg-type]

    def test_verify_password_returns_false_for_invalid_hash(self):
        self.assertFalse(pg_auth_service._verify_password("secret", "not-a-bcrypt-hash"))
