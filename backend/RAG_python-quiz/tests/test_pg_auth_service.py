import unittest
from unittest.mock import patch

from app.services.auth.passwords import hash_password, verify_password
from app.services.auth.refresh_tokens import hash_refresh_token, new_refresh_token
from app.services.auth.service import auth_service
from tests.support import FakeConnection, FakeCursor


def db_patch(conn):
    return patch("app.services.pg.pg_db._get_conn", return_value=conn)


def auth_row(**overrides):
    row = {
        "id": "user-1",
        "email": "u@example.com",
        "role": "teacher",
        "password_hash": hash_password("secret"),
    }
    row.update(overrides)
    return row


class PgAuthServiceTests(unittest.TestCase):
    def test_login_success_updates_last_login_and_returns_token(self):
        cursor = FakeCursor(fetchone_results=[auth_row()])
        conn = FakeConnection(cursor)

        with db_patch(conn), patch(
            "app.services.auth.tokens.create_access_token",
            return_value="access-token",
        ), patch("app.services.auth.service.new_refresh_token", return_value="refresh-token"):
            result = auth_service.login("u@example.com", "secret", "teacher")

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
        self.assertEqual(cursor.executed[2][1][1], hash_refresh_token("refresh-token"))

    def test_login_rejects_invalid_inputs(self):
        cases = (
            ("missing user", [None], ("u@example.com", "secret")),
            ("invalid password", [auth_row()], ("u@example.com", "wrong")),
            ("invalid requested role", [auth_row()], ("u@example.com", "secret", "admin")),
            ("role mismatch", [auth_row()], ("u@example.com", "secret", "student")),
            ("missing user id", [auth_row(id=None)], ("u@example.com", "secret")),
        )
        for name, fetchone_results, args in cases:
            with self.subTest(name=name), db_patch(FakeConnection(FakeCursor(fetchone_results=fetchone_results))):
                with self.assertRaises(ValueError):
                    auth_service.login(*args)

    def test_verify_session_returns_normalized_payload(self):
        with patch("app.services.auth.service.verify_token", return_value={"sub": "user-1", "username": "u@example.com", "exp": 1, "iat": 2}):
            self.assertEqual(
                auth_service.verify_session("token"),
                {"user_id": "user-1", "email": "u@example.com", "exp": 1, "iat": 2},
            )

    def test_verify_session_returns_none_for_invalid_token(self):
        with patch("app.services.auth.service.verify_token", return_value=None):
            self.assertIsNone(auth_service.verify_session("token"))

    def test_refresh_session_rotates_refresh_token_and_returns_new_pair(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"id": "user-1", "email": "u@example.com", "full_name": "User", "role": "teacher"}
            ]
        )
        conn = FakeConnection(cursor)

        with db_patch(conn), patch(
            "app.services.auth.service.new_refresh_token",
            return_value="new-refresh",
        ), patch(
            "app.services.auth.tokens.create_access_token",
            return_value="new-access",
        ):
            result = auth_service.refresh_session("old-refresh")

        self.assertEqual(result["session_token"], "new-access")
        self.assertEqual(result["access_token"], "new-access")
        self.assertEqual(result["refresh_token"], "new-refresh")
        self.assertEqual(result["user"]["id"], "user-1")
        self.assertTrue(conn.committed)
        self.assertIn(
            "app_security.auth_rotate_refresh_token(%s::text, %s::text, %s::timestamptz)",
            cursor.executed[0][0],
        )
        self.assertEqual(cursor.executed[0][1][0], hash_refresh_token("old-refresh"))
        self.assertEqual(cursor.executed[0][1][1], hash_refresh_token("new-refresh"))

    def test_refresh_session_rejects_empty_invalid_or_expired_token(self):
        with self.subTest(name="empty"):
            with self.assertRaises(ValueError):
                auth_service.refresh_session("")

        conn = FakeConnection(FakeCursor(fetchone_results=[None]))
        with self.subTest(name="invalid"), db_patch(conn), patch(
            "app.services.auth.service.new_refresh_token", return_value="new-refresh"
        ):
            with self.assertRaises(ValueError):
                auth_service.refresh_session("old-refresh")

        self.assertTrue(conn.committed)

    def test_logout_revokes_valid_refresh_token(self):
        cursor = FakeCursor(fetchone_results=[{"revoked": True}])
        conn = FakeConnection(cursor)

        with db_patch(conn):
            result = auth_service.logout("refresh-token")

        self.assertEqual(result["message"], "Logout successful")
        self.assertTrue(conn.committed)
        self.assertIn("app_security.auth_revoke_refresh_token(%s::text)", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1][0], hash_refresh_token("refresh-token"))

    def test_logout_rejects_empty_or_invalid_refresh_token(self):
        with self.subTest(name="empty"):
            with self.assertRaises(ValueError):
                auth_service.logout("")

        conn = FakeConnection(FakeCursor(fetchone_results=[{"revoked": False}]))
        with self.subTest(name="invalid"), db_patch(conn):
            with self.assertRaises(ValueError):
                auth_service.logout("refresh-token")

        self.assertTrue(conn.committed)

    def test_register_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            auth_service.register("u@example.com", "secret", "User", "admin")

    def test_register_rejects_existing_email(self):
        cursor = FakeCursor(fetchone_results=[{"exists": True}])
        conn = FakeConnection(cursor)
        with db_patch(conn):
            with self.assertRaises(ValueError):
                auth_service.register("u@example.com", "secret", "User", "student")

    def test_register_creates_users_and_commits(self):
        cases = (
            ("teacher", "u@example.com", "User", "user-1"),
            ("student", "s@example.com", "Student", "user-2"),
        )
        for role, email, full_name, user_id in cases:
            cursor = FakeCursor(
                fetchone_results=[
                    {"exists": False},
                    {"id": user_id, "email": email, "full_name": full_name, "role": role, "created_at": "now"},
                ]
            )
            conn = FakeConnection(cursor)

            with self.subTest(role=role), db_patch(conn):
                result = auth_service.register(email, "secret", full_name, role)

            self.assertEqual(result["user"]["role"], role)
            self.assertTrue(conn.committed)
            self.assertIn("app_security.auth_email_exists(%s::text)", cursor.executed[0][0])
            self.assertIn(
                "app_security.auth_register_user(%s::text, %s::text, %s::text, %s::text)",
                cursor.executed[1][0],
            )

    def test_register_rejects_missing_function_result(self):
        cursor = FakeCursor(fetchone_results=[{"exists": False}, None])
        conn = FakeConnection(cursor)

        with db_patch(conn):
            with self.assertRaises(ValueError):
                auth_service.register("u@example.com", "secret", "User", "student")

    def test_hash_password_requires_string(self):
        with self.assertRaises(TypeError):
            hash_password(123)  # type: ignore[arg-type]

    def test_verify_password_handles_non_string_password(self):
        self.assertFalse(verify_password(123, "hash"))  # type: ignore[arg-type]

    def test_verify_password_returns_false_for_invalid_hash(self):
        self.assertFalse(verify_password("secret", "not-a-bcrypt-hash"))

    def test_new_refresh_token_returns_random_urlsafe_value(self):
        token = new_refresh_token()

        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)
