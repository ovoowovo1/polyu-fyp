import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from app.services.pg import rls_context
from tests.support import make_settings


class MainAppTests(unittest.TestCase):
    def build_logged_client(self, *, raise_server_exceptions=True):
        app = FastAPI()
        main._add_request_logging_middleware(app)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.get("/boom")
        def boom():
            raise RuntimeError("boom")

        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def logged_get(self, client, path="/ok", *, headers=None, level="INFO"):
        with self.assertLogs("api.request", level=level) as logs:
            response = client.get(path, headers=headers or {})
        return response, logs.output[0]

    def assert_log_has(self, message, *parts):
        for part in parts:
            self.assertIn(part, message)

    def test_default_static_dir_points_to_backend_static_folder(self):
        static_dir = Path(main._default_static_dir()).resolve()
        self.assertEqual(static_dir.parts[-3:], ("backend", "RAG_python-quiz", "static"))

    def test_validate_startup_settings_accepts_configured_jwt_secret(self):
        main._validate_startup_settings(make_settings(jwt_secret_key="test-secret"))

    def test_validate_startup_settings_rejects_placeholder_jwt_secret(self):
        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY must be configured"):
            main._validate_startup_settings(make_settings(jwt_secret_key="123456789"))

    def test_create_app_mounts_static_and_registers_routes(self):
        settings = make_settings(cors_origins=["http://localhost:5173"])
        with tempfile.TemporaryDirectory() as tmpdir:
            app = main.create_app(settings=settings, static_dir=tmpdir)

        routes = {route.path for route in app.routes}
        self.assertIn("/files", routes)
        self.assertNotIn("/neo4j/files", routes)
        self.assertIn("/api/query-stream", routes)
        self.assertNotIn("/query-stream", routes)
        self.assertIn("/static", routes)

    def test_create_app_allows_vite_loopback_cors_preflight(self):
        origin = "http://127.0.0.1:5173"
        settings = make_settings(cors_origins=[origin])
        with tempfile.TemporaryDirectory() as tmpdir:
            app = main.create_app(settings=settings, static_dir=tmpdir)

        client = TestClient(app)
        response = client.options(
            "/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")

    def test_main_entrypoint_runs_uvicorn_with_expected_host_and_port(self):
        settings = make_settings(port=4321)
        module_path = Path(main.__file__)

        with patch("app.config.get_settings", return_value=settings), patch("uvicorn.run") as uvicorn_run:
            runpy.run_path(str(module_path), run_name="__main__")

        uvicorn_run.assert_called_once_with("main:app", host="0.0.0.0", port=4321, reload=True)

    def test_request_logging_records_anonymous_without_authorization_header(self):
        client = self.build_logged_client()

        response, message = self.logged_get(client, headers={"user-agent": "test-agent"})

        self.assertEqual(response.status_code, 200)
        self.assert_log_has(
            message,
            "user_id=anonymous",
            "email=anonymous",
            "method=GET",
            "path=/ok",
            "status_code=200",
            "user_agent=test-agent",
        )

    def test_request_logging_records_user_from_bearer_token(self):
        client = self.build_logged_client()
        payload = {"sub": "user-1", "username": "student@example.com"}

        with patch("main.verify_token", return_value=payload) as verify_token:
            response, message = self.logged_get(client, headers={"Authorization": "Bearer good-token"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_called_once_with("good-token")
        self.assert_log_has(message, "user_id=user-1", "email=student@example.com")
        self.assertNotIn("good-token", message)

    def test_request_logging_uses_anonymous_for_invalid_token(self):
        client = self.build_logged_client()

        with patch("main.verify_token", return_value=None) as verify_token:
            response, message = self.logged_get(client, headers={"Authorization": "Bearer bad-token"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_called_once_with("bad-token")
        self.assert_log_has(message, "user_id=anonymous", "email=anonymous")
        self.assertNotIn("bad-token", message)

    def test_request_logging_uses_anonymous_for_malformed_authorization_header(self):
        client = self.build_logged_client()

        with patch("main.verify_token") as verify_token:
            response, message = self.logged_get(client, headers={"Authorization": "Basic abc"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_not_called()
        self.assertIn("user_id=anonymous", message)

    def test_request_logging_uses_anonymous_for_token_without_subject(self):
        client = self.build_logged_client()

        with patch("main.verify_token", return_value={"username": "student@example.com"}):
            response, message = self.logged_get(client, headers={"Authorization": "Bearer no-sub-token"})

        self.assertEqual(response.status_code, 200)
        self.assert_log_has(message, "user_id=anonymous", "email=anonymous")

    def test_request_logging_prefers_forwarded_client_ip(self):
        client = self.build_logged_client()

        response, message = self.logged_get(client, headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("client_ip=203.0.113.7", message)

    def test_request_logging_records_exception_and_preserves_error_response(self):
        client = self.build_logged_client(raise_server_exceptions=False)

        response, message = self.logged_get(client, path="/boom", level="ERROR")

        self.assertEqual(response.status_code, 500)
        self.assert_log_has(message, "user_id=anonymous", "method=GET", "path=/boom", "status_code=error")

    def test_request_logging_middleware_clears_rls_context_after_request(self):
        app = FastAPI()
        main._add_request_logging_middleware(app)

        @app.get("/set-context")
        def set_context():
            rls_context.set_current_rls_user("user-1")
            return {"ok": True}

        client = TestClient(app)
        with self.assertLogs("api.request", level="INFO"):
            response = client.get("/set-context")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(rls_context.get_current_rls_user())
