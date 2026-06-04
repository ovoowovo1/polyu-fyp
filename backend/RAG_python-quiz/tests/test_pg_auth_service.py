import unittest
from unittest.mock import patch

from app.services.pg import pg_auth_service
from tests.support import FakeConnection, FakeCursor


class PgAuthServiceTests(unittest.TestCase):
    def test_login_success_updates_last_login_and_returns_token(self):
        cursor = FakeCursor(fetchone_results=[{"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}])
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn), patch(
            "app.services.pg.pg_auth_service.create_access_token",
            return_value="access-token",
        ), patch("app.services.pg.pg_auth_service._new_refresh_token", return_value="refresh-token"):
            result = pg_auth_service.login("u@example.com", "secret", "teacher")

        self.assertEqual(result["session_token"], "access-token")
        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(result["refresh_token"], "refresh-token")
        self.assertEqual(result["expires_in"], 900)
        self.assertEqual(result["token_type"], "Bearer")
        self.assertTrue(conn.committed)
        self.assertNotIn("password_hash", result["user"])
        self.assertIn("app_security.auth_lookup_user(%s::text)", cursor.executed[0][0])
        self.assertIn("app_security.auth_mark_last_login(%s::uuid)", cursor.executed[1][0])
        self.assertIn(
            "app_security.auth_store_refresh_token(%s::uuid, %s::text, %s::timestamptz)",
            cursor.executed[2][0],
        )
        self.assertEqual(cursor.executed[2][1][0], "user-1")
        self.assertEqual(cursor.executed[2][1][1], pg_auth_service._hash_refresh_token("refresh-token"))

    def test_login_raises_when_user_missing(self):
        with patch("app.services.pg.pg_db._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[None]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret")

    def test_login_raises_for_invalid_password(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg.pg_db._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "wrong")

    def test_login_rejects_invalid_requested_role(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg.pg_db._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret", "admin")

    def test_login_rejects_role_mismatch(self):
        row = {"id": "user-1", "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg.pg_db._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret", "student")

    def test_login_rejects_missing_user_id(self):
        row = {"id": None, "email": "u@example.com", "role": "teacher", "password_hash": pg_auth_service._hash_password("secret")}
        with patch("app.services.pg.pg_db._get_conn", return_value=FakeConnection(FakeCursor(fetchone_results=[row]))):
            with self.assertRaises(ValueError):
                pg_auth_service.login("u@example.com", "secret")

    def test_verify_session_returns_normalized_payload(self):
        with patch("app.services.pg.pg_auth_service.verify_token", return_value={"sub": "user-1", "username": "u@example.com", "exp": 1, "iat": 2}):
            self.assertEqual(
                pg_auth_service.verify_session("token"),
                {"user_id": "user-1", "email": "u@example.com", "exp": 1, "iat": 2},
            )

    def test_verify_session_returns_none_for_invalid_token(self):
        with patch("app.services.pg.pg_auth_service.verify_token", return_value=None):
            self.assertIsNone(pg_auth_service.verify_session("token"))

    def test_refresh_session_rotates_refresh_token_and_returns_new_pair(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"id": "user-1", "email": "u@example.com", "full_name": "User", "role": "teacher"}
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn), patch(
            "app.services.pg.pg_auth_service._new_refresh_token",
            return_value="new-refresh",
        ), patch(
            "app.services.pg.pg_auth_service.create_access_token",
            return_value="new-access",
        ):
            result = pg_auth_service.refresh_session("old-refresh")

        self.assertEqual(result["session_token"], "new-access")
        self.assertEqual(result["access_token"], "new-access")
        self.assertEqual(result["refresh_token"], "new-refresh")
        self.assertEqual(result["user"]["id"], "user-1")
        self.assertTrue(conn.committed)
        self.assertIn(
            "app_security.auth_rotate_refresh_token(%s::text, %s::text, %s::timestamptz)",
            cursor.executed[0][0],
        )
        self.assertEqual(cursor.executed[0][1][0], pg_auth_service._hash_refresh_token("old-refresh"))
        self.assertEqual(cursor.executed[0][1][1], pg_auth_service._hash_refresh_token("new-refresh"))

    def test_refresh_session_rejects_empty_token(self):
        with self.assertRaises(ValueError):
            pg_auth_service.refresh_session("")

    def test_refresh_session_rejects_invalid_or_expired_token(self):
        conn = FakeConnection(FakeCursor(fetchone_results=[None]))
        with patch("app.services.pg.pg_db._get_conn", return_value=conn), patch(
            "app.services.pg.pg_auth_service._new_refresh_token",
            return_value="new-refresh",
        ):
            with self.assertRaises(ValueError):
                pg_auth_service.refresh_session("old-refresh")

        self.assertTrue(conn.committed)

    def test_logout_revokes_valid_refresh_token(self):
        cursor = FakeCursor(fetchone_results=[{"revoked": True}])
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            result = pg_auth_service.logout("refresh-token")

        self.assertEqual(result["message"], "Logout successful")
        self.assertTrue(conn.committed)
        self.assertIn("app_security.auth_revoke_refresh_token(%s::text)", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1][0], pg_auth_service._hash_refresh_token("refresh-token"))

    def test_logout_rejects_empty_refresh_token(self):
        with self.assertRaises(ValueError):
            pg_auth_service.logout("")

    def test_logout_rejects_invalid_refresh_token(self):
        conn = FakeConnection(FakeCursor(fetchone_results=[{"revoked": False}]))
        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            with self.assertRaises(ValueError):
                pg_auth_service.logout("refresh-token")

        self.assertTrue(conn.committed)

    def test_register_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            pg_auth_service.register("u@example.com", "secret", "User", "admin")

    def test_register_rejects_existing_email(self):
        cursor = FakeCursor(fetchone_results=[{"exists": True}])
        conn = FakeConnection(cursor)
        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            with self.assertRaises(ValueError):
                pg_auth_service.register("u@example.com", "secret", "User", "student")

    def test_register_creates_teacher_and_commits(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"exists": False},
                {"id": "user-1", "email": "u@example.com", "full_name": "User", "role": "teacher", "created_at": "now"},
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            result = pg_auth_service.register("u@example.com", "secret", "User", "teacher")

        self.assertEqual(result["user"]["role"], "teacher")
        self.assertTrue(conn.committed)
        self.assertIn("app_security.auth_email_exists(%s::text)", cursor.executed[0][0])
        self.assertIn(
            "app_security.auth_register_user(%s::text, %s::text, %s::text, %s::text)",
            cursor.executed[1][0],
        )

    def test_register_creates_student_and_commits(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"exists": False},
                {"id": "user-2", "email": "s@example.com", "full_name": "Student", "role": "student", "created_at": "now"},
            ]
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            result = pg_auth_service.register("s@example.com", "secret", "Student", "student")

        self.assertEqual(result["user"]["role"], "student")
        self.assertTrue(conn.committed)

    def test_register_rejects_missing_function_result(self):
        cursor = FakeCursor(fetchone_results=[{"exists": False}, None])
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            with self.assertRaises(ValueError):
                pg_auth_service.register("u@example.com", "secret", "User", "student")

    def test_hash_password_requires_string(self):
        with self.assertRaises(TypeError):
            pg_auth_service._hash_password(123)  # type: ignore[arg-type]

    def test_verify_password_handles_non_string_password(self):
        self.assertFalse(pg_auth_service._verify_password(123, "hash"))  # type: ignore[arg-type]

    def test_verify_password_returns_false_for_invalid_hash(self):
        self.assertFalse(pg_auth_service._verify_password("secret", "not-a-bcrypt-hash"))

    def test_new_refresh_token_returns_random_urlsafe_value(self):
        token = pg_auth_service._new_refresh_token()

        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)
