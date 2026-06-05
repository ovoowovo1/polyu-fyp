import unittest
from unittest.mock import patch

from app.routers import auth
from tests.support import build_client


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(auth.router)

    def assert_post_error(self, patch_target, side_effect, path, payload, expected_status, expected_error):
        with patch(patch_target, side_effect=side_effect):
            response = self.client.post(path, json=payload)

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.json()["detail"]["error"], expected_error)

    def test_login_success(self):
        with patch(
            "app.routers.auth.auth_login",
            return_value={
                "session_token": "access-token",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 900,
                "token_type": "Bearer",
            },
        ):
            response = self.client.post(
                "/auth/login",
                json={"email": "teacher@example.com", "password": "secret", "role": "teacher"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_token"], "access-token")
        self.assertEqual(response.json()["access_token"], "access-token")
        self.assertEqual(response.json()["refresh_token"], "refresh-token")
        self.assertEqual(response.json()["message"], "Login successful")
        self.assertEqual(response.json()["data"]["session_token"], "access-token")

    def test_register_success(self):
        with patch("app.routers.auth.auth_register", return_value={"message": "ok"}):
            response = self.client.post(
                "/auth/register",
                json={
                    "email": "student@example.com",
                    "password": "secret",
                    "full_name": "Student Name",
                    "role": "student",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "ok")
        self.assertEqual(response.json()["data"]["message"], "ok")

    def test_verify_returns_payload_fields(self):
        with patch("app.routers.auth.verify_token", return_value={"sub": "user-1", "username": "u@example.com"}):
            response = self.client.get("/auth/verify", headers={"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        self.assertEqual(response.json()["user_id"], "user-1")
        self.assertEqual(response.json()["email"], "u@example.com")
        self.assertEqual(response.json()["message"], "Token verified")
        self.assertTrue(response.json()["data"]["valid"])

    def test_verify_rejects_invalid_or_missing_token(self):
        cases = (
            ({"Authorization": "Bearer invalid-token"}, "Invalid or expired token", True),
            ({}, "Authorization header missing", False),
        )
        for headers, expected_error, patch_verify in cases:
            with self.subTest(expected_error=expected_error):
                if patch_verify:
                    with patch("app.routers.auth.verify_token", return_value=None):
                        response = self.client.get("/auth/verify", headers=headers)
                else:
                    response = self.client.get("/auth/verify", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"]["error"], expected_error)

    def test_refresh_success_returns_new_tokens(self):
        with patch(
            "app.routers.auth.auth_refresh_session",
            return_value={
                "session_token": "new-access",
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 900,
                "token_type": "Bearer",
            },
        ) as refresh_session:
            response = self.client.post("/auth/refresh", json={"refresh_token": "old-refresh"})

        self.assertEqual(response.status_code, 200)
        refresh_session.assert_called_once_with("old-refresh")
        self.assertEqual(response.json()["message"], "Token refreshed")
        self.assertEqual(response.json()["session_token"], "new-access")
        self.assertEqual(response.json()["refresh_token"], "new-refresh")

    def test_logout_success_revokes_refresh_token(self):
        with patch("app.routers.auth.auth_logout", return_value={"message": "Logout successful"}) as logout:
            response = self.client.post("/auth/logout", json={"refresh_token": "refresh"})

        self.assertEqual(response.status_code, 200)
        logout.assert_called_once_with("refresh")
        self.assertEqual(response.json()["message"], "Logout successful")

    def test_service_errors_return_expected_status(self):
        login_payload = {"email": "teacher@example.com", "password": "secret"}
        register_payload = {"email": "student@example.com", "password": "secret", "full_name": "Student Name"}
        cases = (
            ("app.routers.auth.auth_login", ValueError("bad credentials"), "/auth/login", login_payload, 401, "bad credentials"),
            ("app.routers.auth.auth_login", RuntimeError("db down"), "/auth/login", login_payload, 500, "Login failed"),
            ("app.routers.auth.auth_register", ValueError("duplicate"), "/auth/register", register_payload, 400, "duplicate"),
            ("app.routers.auth.auth_register", RuntimeError("db down"), "/auth/register", register_payload, 500, "Register failed"),
            ("app.routers.auth.auth_refresh_session", ValueError("Invalid refresh token"), "/auth/refresh", {"refresh_token": "bad-refresh"}, 401, "Invalid refresh token"),
            ("app.routers.auth.auth_refresh_session", RuntimeError("db down"), "/auth/refresh", {"refresh_token": "refresh"}, 500, "Refresh failed"),
            ("app.routers.auth.auth_logout", ValueError("Invalid refresh token"), "/auth/logout", {"refresh_token": "bad-refresh"}, 401, "Invalid refresh token"),
            ("app.routers.auth.auth_logout", RuntimeError("db down"), "/auth/logout", {"refresh_token": "refresh"}, 500, "Logout failed"),
        )
        for patch_target, side_effect, path, payload, status, error in cases:
            with self.subTest(path=path, error=error):
                self.assert_post_error(patch_target, side_effect, path, payload, status, error)
