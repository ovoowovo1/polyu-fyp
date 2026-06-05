import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from app.services.pg import rls_context
from app.services.auth import tokens as auth_tokens
from app.utils import jwt_utils
from tests.support import make_settings

UNPATCHED = object()


class JwtUtilsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = make_settings(jwt_secret_key="secret")

    def test_create_token_helpers_verify_round_trip_as_access_tokens(self):
        cases = (
            (jwt_utils.create_session_token, {"expires_in_days": 1}),
            (jwt_utils.create_access_token, {}),
        )

        for create_token, kwargs in cases:
            with self.subTest(create_token=create_token.__name__), patch("app.utils.jwt_utils.get_settings", return_value=self.settings):
                token = create_token("user-1", "u@example.com", **kwargs)
                payload = jwt_utils.verify_token(token)

            self.assertEqual(payload["sub"], "user-1")
            self.assertEqual(payload["username"], "u@example.com")
            self.assertEqual(payload["type"], "access")

    def test_create_session_token_rejects_placeholder_secret(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=make_settings(jwt_secret_key="change-me")):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY must be configured"):
                jwt_utils.create_session_token("user-1", "u@example.com")

    def test_validate_jwt_secret_config_accepts_explicit_test_secret(self):
        auth_tokens.validate_jwt_secret_config(make_settings(jwt_secret_key="test-secret"))

    def test_validate_jwt_secret_config_rejects_missing_secret(self):
        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY must be configured"):
            auth_tokens.validate_jwt_secret_config(make_settings(jwt_secret_key=""))

    def test_verify_token_returns_none_for_placeholder_secret(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=make_settings(jwt_secret_key="123456789")):
            with self.assertLogs("app.utils.jwt_utils", level="WARNING") as logs:
                self.assertIsNone(jwt_utils.verify_token("token"))

        self.assertIn("JWT_SECRET_KEY must be configured", logs.output[0])

    def test_verify_token_returns_none_for_invalid_token(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings):
            self.assertIsNone(jwt_utils.verify_token("not-a-token"))

    def test_verify_token_rejects_non_access_token_type(self):
        payload = {
            "sub": "user-1",
            "username": "u@example.com",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=5),
            "type": "refresh",
        }
        token = jwt.encode(payload, self.settings.jwt_secret_key, algorithm="HS256")

        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings):
            self.assertIsNone(jwt_utils.verify_token(token))

    def test_verify_token_returns_none_for_unexpected_decode_error(self):
        with patch("app.utils.jwt_utils.get_settings", return_value=self.settings), patch(
            "app.utils.jwt_utils.jwt.decode",
            side_effect=RuntimeError("boom"),
        ):
            self.assertIsNone(jwt_utils.verify_token("token"))

    async def test_get_current_user_rejects_invalid_inputs(self):
        cases = (
            (None, UNPATCHED, "Authorization header missing"),
            (HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad"), None, "Invalid or expired token"),
            (
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="good"),
                {"username": "u@example.com"},
                "Invalid token payload",
            ),
        )
        for creds, verify_payload, expected_error in cases:
            verify_context = (
                nullcontext()
                if verify_payload is UNPATCHED
                else patch("app.utils.jwt_utils.verify_token", return_value=verify_payload)
            )
            with self.subTest(expected_error=expected_error), verify_context:
                with self.assertRaises(HTTPException) as ctx:
                    await jwt_utils.get_current_user(creds)

                self.assertEqual(ctx.exception.status_code, 401)
                self.assertEqual(ctx.exception.detail["error"], expected_error)

    async def test_get_current_user_returns_normalized_payload(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good")
        payload = {"sub": "user-1", "username": "u@example.com"}
        rls_context.clear_current_rls_user()
        with patch("app.utils.jwt_utils.verify_token", return_value=payload):
            user = await jwt_utils.get_current_user(creds)

        self.assertEqual(
            user,
            {
                "token": "good",
                "user_id": "user-1",
                "email": "u@example.com",
                "payload": payload,
            },
        )
        self.assertEqual(rls_context.get_current_rls_user(), "user-1")
        rls_context.clear_current_rls_user()
