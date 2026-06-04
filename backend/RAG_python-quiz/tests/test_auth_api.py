import unittest
from unittest.mock import patch

from app.routers import auth
from tests.support import build_client


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(auth.router)

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

    def test_login_invalid_credentials_returns_401(self):
        with patch("app.routers.auth.auth_login", side_effect=ValueError("bad credentials")):
            response = self.client.post(
                "/auth/login",
                json={"email": "teacher@example.com", "password": "secret"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "bad credentials")

    def test_login_unexpected_error_returns_500(self):
        with patch("app.routers.auth.auth_login", side_effect=RuntimeError("db down")):
            response = self.client.post(
                "/auth/login",
                json={"email": "teacher@example.com", "password": "secret"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "Login failed")

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

    def test_register_value_error_returns_400(self):
        with patch("app.routers.auth.auth_register", side_effect=ValueError("duplicate")):
            response = self.client.post(
                "/auth/register",
                json={
                    "email": "student@example.com",
                    "password": "secret",
                    "full_name": "Student Name",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "duplicate")

    def test_register_unexpected_error_returns_500(self):
        with patch("app.routers.auth.auth_register", side_effect=RuntimeError("db down")):
            response = self.client.post(
                "/auth/register",
                json={
                    "email": "student@example.com",
                    "password": "secret",
                    "full_name": "Student Name",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "Register failed")

    def test_verify_returns_payload_fields(self):
        with patch("app.routers.auth.verify_token", return_value={"sub": "user-1", "username": "u@example.com"}):
            response = self.client.get("/auth/verify", headers={"Authorization": "Bearer valid-token"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        self.assertEqual(response.json()["user_id"], "user-1")
        self.assertEqual(response.json()["email"], "u@example.com")
        self.assertEqual(response.json()["message"], "Token verified")
        self.assertTrue(response.json()["data"]["valid"])

    def test_verify_rejects_invalid_token(self):
        with patch("app.routers.auth.verify_token", return_value=None):
            response = self.client.get("/auth/verify", headers={"Authorization": "Bearer invalid-token"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "Invalid or expired token")

    def test_verify_rejects_missing_authorization_header(self):
        response = self.client.get("/auth/verify")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "Authorization header missing")

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

    def test_refresh_rejects_invalid_token(self):
        with patch("app.routers.auth.auth_refresh_session", side_effect=ValueError("Invalid refresh token")):
            response = self.client.post("/auth/refresh", json={"refresh_token": "bad-refresh"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "Invalid refresh token")

    def test_refresh_unexpected_error_returns_500(self):
        with patch("app.routers.auth.auth_refresh_session", side_effect=RuntimeError("db down")):
            response = self.client.post("/auth/refresh", json={"refresh_token": "refresh"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "Refresh failed")

    def test_logout_success_revokes_refresh_token(self):
        with patch("app.routers.auth.auth_logout", return_value={"message": "Logout successful"}) as logout:
            response = self.client.post("/auth/logout", json={"refresh_token": "refresh"})

        self.assertEqual(response.status_code, 200)
        logout.assert_called_once_with("refresh")
        self.assertEqual(response.json()["message"], "Logout successful")

    def test_logout_rejects_invalid_refresh_token(self):
        with patch("app.routers.auth.auth_logout", side_effect=ValueError("Invalid refresh token")):
            response = self.client.post("/auth/logout", json={"refresh_token": "bad-refresh"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "Invalid refresh token")

    def test_logout_unexpected_error_returns_500(self):
        with patch("app.routers.auth.auth_logout", side_effect=RuntimeError("db down")):
            response = self.client.post("/auth/logout", json={"refresh_token": "refresh"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "Logout failed")
