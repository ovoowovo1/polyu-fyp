import unittest
from unittest.mock import patch

from app.routers import auth
from tests.support import build_client


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(auth.router)

    def test_login_success(self):
        with patch("app.routers.auth.auth_login", return_value={"session_token": "token"}):
            response = self.client.post(
                "/auth/login",
                json={"email": "teacher@example.com", "password": "secret", "role": "teacher"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_token"], "token")

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
        self.assertEqual(
            response.json(),
            {"valid": True, "user_id": "user-1", "email": "u@example.com"},
        )

    def test_verify_rejects_invalid_token(self):
        with patch("app.routers.auth.verify_token", return_value=None):
            response = self.client.get("/auth/verify", headers={"Authorization": "Bearer invalid-token"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "Invalid or expired token")
