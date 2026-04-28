import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.utils import jwt_utils


class JwtUtilsTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(jwt_secret_key="secret")

    def test_create_session_token_and_verify_token_round_trip(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings):
            token = jwt_utils.create_session_token("user-1", "u@example.com", expires_in_days=1)
            payload = jwt_utils.verify_token(token)

        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["username"], "u@example.com")

    def test_verify_token_returns_none_for_invalid_token(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings):
            self.assertIsNone(jwt_utils.verify_token("not-a-token"))

    def test_verify_token_returns_none_for_unexpected_decode_error(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings), patch(
            "app.utils.jwt_utils.jwt.decode",
            side_effect=RuntimeError("boom"),
        ):
            self.assertIsNone(jwt_utils.verify_token("token"))

    def test_get_user_id_from_token_returns_none_for_invalid_token(self):
        with patch("app.utils.jwt_utils.verify_token", return_value=None):
            self.assertIsNone(jwt_utils.get_user_id_from_token("bad"))

    def test_get_user_id_from_token_returns_subject(self):
        with patch("app.utils.jwt_utils.verify_token", return_value={"sub": "user-1"}):
            self.assertEqual(jwt_utils.get_user_id_from_token("good"), "user-1")

    def test_get_current_user_requires_credentials(self):
        with self.assertRaises(HTTPException) as ctx:
            jwt_utils.get_current_user(None)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["error"], "Authorization header missing")

    def test_get_current_user_rejects_invalid_token(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad")
        with patch("app.utils.jwt_utils.verify_token", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                jwt_utils.get_current_user(creds)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["error"], "Invalid or expired token")

    def test_get_current_user_rejects_missing_subject(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good")
        with patch("app.utils.jwt_utils.verify_token", return_value={"username": "u@example.com"}):
            with self.assertRaises(HTTPException) as ctx:
                jwt_utils.get_current_user(creds)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail["error"], "Invalid token payload")

    def test_get_current_user_returns_normalized_payload(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good")
        payload = {"sub": "user-1", "username": "u@example.com"}
        with patch("app.utils.jwt_utils.verify_token", return_value=payload):
            user = jwt_utils.get_current_user(creds)

        self.assertEqual(
            user,
            {
                "token": "good",
                "user_id": "user-1",
                "email": "u@example.com",
                "payload": payload,
            },
        )
